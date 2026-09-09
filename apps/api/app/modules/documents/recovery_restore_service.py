from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    S3CompatibleEvidenceStore,
)
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationNotFound,
    RecoveryReplicationUnavailable,
    _assert_replica_matches_source,
    _build_store,
    _load_document_for_update,
    _snapshot_local,
    _utc_iso,
    get_document_recovery_replica,
)
from app.modules.documents.recovery_restore_models import (
    EvidenceRecoveryRestoreRehearsal,
    EvidenceRecoveryRestoreVerification,
)


class RecoveryRestoreError(RuntimeError):
    pass


class RecoveryRestoreNotFound(RecoveryRestoreError):
    pass


class RecoveryRestoreConflict(RecoveryRestoreError):
    pass


class RecoveryRestoreUnavailable(RecoveryRestoreError):
    pass


@dataclass(frozen=True)
class StagedRestoreSnapshot:
    file_hash: str
    file_size_bytes: int
    staging_storage_key: str
    staging_storage_key_fingerprint: str


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _staging_key(replica: EvidenceRecoveryReplica) -> str:
    return (
        f"recovery-restore-staging/{replica.organization_id}/{replica.claim_id}/"
        f"{replica.document_id}/{replica.id}.restore"
    )


def _staging_path(storage_key: str) -> Path:
    settings = get_settings()
    root = Path(settings.local_storage_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / storage_key).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise RecoveryRestoreConflict("Restore staging key escapes local storage root") from exc
    if not relative.parts or relative.parts[0] != "recovery-restore-staging":
        raise RecoveryRestoreConflict("Restore target is outside the isolated staging namespace")
    return candidate


def _verify_file(path: Path, *, expected_hash: str, expected_size: int) -> tuple[str, int]:
    try:
        payload = path.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise RecoveryRestoreConflict("Recovery restore staging bytes are unavailable") from exc
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_hash.lower():
        raise RecoveryRestoreConflict("Recovery restore staging hash does not match pinned evidence")
    if len(payload) != expected_size:
        raise RecoveryRestoreConflict("Recovery restore staging size does not match pinned evidence")
    return digest, len(payload)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_staging_if_absent(
    payload: bytes,
    *,
    staging_storage_key: str,
    expected_hash: str,
    expected_size: int,
) -> StagedRestoreSnapshot:
    if hashlib.sha256(payload).hexdigest() != expected_hash.lower() or len(payload) != expected_size:
        raise RecoveryRestoreConflict("Verified remote payload changed before staging")

    destination = _staging_path(staging_storage_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RecoveryRestoreConflict(
            "Recovery restore staging target already exists without a reusable rehearsal lineage"
        )

    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    linked = False
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        _verify_file(temporary, expected_hash=expected_hash, expected_size=expected_size)
        try:
            os.link(temporary, destination)
            linked = True
        except FileExistsError as exc:
            raise RecoveryRestoreConflict(
                "Recovery restore staging target was claimed concurrently"
            ) from exc
        except OSError as exc:
            raise RecoveryRestoreUnavailable(
                f"Atomic recovery staging publish failed: {type(exc).__name__}"
            ) from exc
        _fsync_directory(destination.parent)
    finally:
        # Only the isolated temporary staging artifact is cleaned up. Authoritative
        # evidence and recovery replica objects are never removed by this service.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

    if not linked:
        raise RecoveryRestoreUnavailable("Recovery restore staging publish did not complete")
    digest, size = _verify_file(
        destination,
        expected_hash=expected_hash,
        expected_size=expected_size,
    )
    return StagedRestoreSnapshot(
        file_hash=digest,
        file_size_bytes=size,
        staging_storage_key=staging_storage_key,
        staging_storage_key_fingerprint=_fingerprint(staging_storage_key),
    )


def _verify_staging(
    rehearsal: EvidenceRecoveryRestoreRehearsal,
) -> StagedRestoreSnapshot:
    expected_key = _staging_key_from_rehearsal(rehearsal)
    if rehearsal.staging_storage_key != expected_key:
        raise RecoveryRestoreConflict("Pinned recovery staging key lineage drifted")
    if rehearsal.staging_storage_key_fingerprint != _fingerprint(expected_key):
        raise RecoveryRestoreConflict("Pinned recovery staging key fingerprint drifted")
    digest, size = _verify_file(
        _staging_path(expected_key),
        expected_hash=rehearsal.source_file_hash,
        expected_size=rehearsal.source_file_size_bytes,
    )
    return StagedRestoreSnapshot(
        file_hash=digest,
        file_size_bytes=size,
        staging_storage_key=expected_key,
        staging_storage_key_fingerprint=rehearsal.staging_storage_key_fingerprint,
    )


def _staging_key_from_rehearsal(rehearsal: EvidenceRecoveryRestoreRehearsal) -> str:
    return (
        f"recovery-restore-staging/{rehearsal.organization_id}/{rehearsal.claim_id}/"
        f"{rehearsal.document_id}/{rehearsal.replica_id}.restore"
    )


def _download_verified_remote(
    store: S3CompatibleEvidenceStore,
    replica: EvidenceRecoveryReplica,
):
    try:
        metadata = store.head_object(storage_key=replica.recovery_storage_key)
        if (
            metadata.file_hash != replica.source_file_hash
            or metadata.file_size_bytes != replica.source_file_size_bytes
        ):
            raise RecoveryRestoreConflict(
                "Recovery replica metadata does not match pinned authoritative evidence"
            )
        payload = store.get_bytes(
            storage_key=replica.recovery_storage_key,
            expected_sha256=replica.source_file_hash,
        )
    except ObjectStorageNotFound as exc:
        raise RecoveryRestoreConflict("Recovery replica object is missing") from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryRestoreConflict("Recovery replica failed integrity verification") from exc
    except ObjectStorageError as exc:
        raise RecoveryRestoreUnavailable("Recovery storage download is unavailable") from exc
    if len(payload) != replica.source_file_size_bytes:
        raise RecoveryRestoreConflict("Recovery replica byte length does not match pinned evidence")
    return metadata, payload


def _load_verified_context(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
):
    try:
        document = _load_document_for_update(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        replica = get_document_recovery_replica(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        snapshot = _snapshot_local(document)
        _assert_replica_matches_source(replica, snapshot)
        store = _build_store()
    except RecoveryReplicationNotFound as exc:
        raise RecoveryRestoreNotFound(str(exc)) from exc
    except RecoveryReplicationConflict as exc:
        raise RecoveryRestoreConflict(str(exc)) from exc
    except RecoveryReplicationUnavailable as exc:
        raise RecoveryRestoreUnavailable(str(exc)) from exc

    if replica.recovery_bucket_fingerprint != store.sanitized_health_identity.bucket_fingerprint:
        raise RecoveryRestoreConflict("Configured recovery bucket changed after replica lineage was pinned")
    metadata, payload = _download_verified_remote(store, replica)
    return document, replica, snapshot, metadata, payload


def _assert_rehearsal_lineage(
    rehearsal: EvidenceRecoveryRestoreRehearsal,
    *,
    replica: EvidenceRecoveryReplica,
    snapshot,
) -> None:
    expected_recovery_key_fp = _fingerprint(replica.recovery_storage_key)
    expected_staging_key = _staging_key(replica)
    expected = (
        rehearsal.replica_id == replica.id
        and rehearsal.replica_hash == replica.replica_hash
        and rehearsal.source_file_hash == snapshot.file_hash
        and rehearsal.source_file_size_bytes == snapshot.file_size_bytes
        and _utc_iso(rehearsal.source_document_updated_at) == _utc_iso(snapshot.document_updated_at)
        and rehearsal.source_storage_key_fingerprint == snapshot.storage_key_fingerprint
        and rehearsal.recovery_bucket_fingerprint == replica.recovery_bucket_fingerprint
        and rehearsal.recovery_storage_key_fingerprint == expected_recovery_key_fp
        and rehearsal.staging_storage_key == expected_staging_key
        and rehearsal.staging_storage_key_fingerprint == _fingerprint(expected_staging_key)
        and rehearsal.restored_file_hash == snapshot.file_hash
        and rehearsal.restored_file_size_bytes == snapshot.file_size_bytes
    )
    if not expected:
        raise RecoveryRestoreConflict("Recovery restore rehearsal lineage drifted from pinned evidence")


def _new_verification(
    *,
    rehearsal: EvidenceRecoveryRestoreRehearsal,
    metadata,
    staged: StagedRestoreSnapshot,
    verified_by_id: UUID,
    reason: str,
    verified_at: datetime,
) -> EvidenceRecoveryRestoreVerification:
    verification_hash = _canonical_hash(
        {
            "rehearsal_id": str(rehearsal.id),
            "replica_id": str(rehearsal.replica_id),
            "document_id": str(rehearsal.document_id),
            "expected_file_hash": rehearsal.source_file_hash,
            "expected_file_size_bytes": rehearsal.source_file_size_bytes,
            "remote_file_hash": metadata.file_hash,
            "remote_file_size_bytes": metadata.file_size_bytes,
            "staged_file_hash": staged.file_hash,
            "staged_file_size_bytes": staged.file_size_bytes,
            "recovery_bucket_fingerprint": rehearsal.recovery_bucket_fingerprint,
            "staging_storage_key_fingerprint": staged.staging_storage_key_fingerprint,
            "remote_etag": metadata.etag,
            "verified_by_id": str(verified_by_id),
            "verified_at": _utc_iso(verified_at),
            "reason": reason.strip(),
        }
    )
    return EvidenceRecoveryRestoreVerification(
        organization_id=rehearsal.organization_id,
        claim_id=rehearsal.claim_id,
        document_id=rehearsal.document_id,
        replica_id=rehearsal.replica_id,
        rehearsal_id=rehearsal.id,
        expected_file_hash=rehearsal.source_file_hash,
        expected_file_size_bytes=rehearsal.source_file_size_bytes,
        remote_file_hash=metadata.file_hash,
        remote_file_size_bytes=metadata.file_size_bytes,
        staged_file_hash=staged.file_hash,
        staged_file_size_bytes=staged.file_size_bytes,
        recovery_bucket_fingerprint=rehearsal.recovery_bucket_fingerprint,
        staging_storage_key_fingerprint=staged.staging_storage_key_fingerprint,
        remote_etag=metadata.etag,
        verification_reason=reason.strip(),
        verification_hash=verification_hash,
        verified_by_id=verified_by_id,
        verified_at=verified_at,
    )


def rehearse_document_recovery_restore(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    restored_by_id: UUID,
    reason: str,
) -> tuple[EvidenceRecoveryRestoreRehearsal, EvidenceRecoveryRestoreVerification, bool]:
    _document, replica, snapshot, metadata, payload = _load_verified_context(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryRestoreRehearsal).where(
            EvidenceRecoveryRestoreRehearsal.organization_id == organization_id,
            EvidenceRecoveryRestoreRehearsal.claim_id == claim_id,
            EvidenceRecoveryRestoreRehearsal.document_id == document_id,
            EvidenceRecoveryRestoreRehearsal.replica_id == replica.id,
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        _assert_rehearsal_lineage(existing, replica=replica, snapshot=snapshot)
        staged = _verify_staging(existing)
        verification = _new_verification(
            rehearsal=existing,
            metadata=metadata,
            staged=staged,
            verified_by_id=restored_by_id,
            reason=reason,
            verified_at=now,
        )
        db.add(verification)
        db.flush()
        return existing, verification, False

    staging_key = _staging_key(replica)
    staged = _write_staging_if_absent(
        payload,
        staging_storage_key=staging_key,
        expected_hash=replica.source_file_hash,
        expected_size=replica.source_file_size_bytes,
    )
    rehearsal_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "replica_id": str(replica.id),
            "replica_hash": replica.replica_hash,
            "source_file_hash": snapshot.file_hash,
            "source_file_size_bytes": snapshot.file_size_bytes,
            "source_document_updated_at": _utc_iso(snapshot.document_updated_at),
            "source_storage_key_fingerprint": snapshot.storage_key_fingerprint,
            "recovery_bucket_fingerprint": replica.recovery_bucket_fingerprint,
            "recovery_storage_key_fingerprint": _fingerprint(replica.recovery_storage_key),
            "staging_storage_key_fingerprint": staged.staging_storage_key_fingerprint,
            "restored_file_hash": staged.file_hash,
            "restored_file_size_bytes": staged.file_size_bytes,
            "remote_etag": metadata.etag,
            "restored_by_id": str(restored_by_id),
            "restored_at": _utc_iso(now),
        }
    )
    rehearsal = EvidenceRecoveryRestoreRehearsal(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        replica_id=replica.id,
        replica_hash=replica.replica_hash,
        source_file_hash=snapshot.file_hash,
        source_file_size_bytes=snapshot.file_size_bytes,
        source_document_updated_at=snapshot.document_updated_at,
        source_storage_key_fingerprint=snapshot.storage_key_fingerprint,
        recovery_bucket_fingerprint=replica.recovery_bucket_fingerprint,
        recovery_storage_key_fingerprint=_fingerprint(replica.recovery_storage_key),
        staging_storage_key=staged.staging_storage_key,
        staging_storage_key_fingerprint=staged.staging_storage_key_fingerprint,
        restored_file_hash=staged.file_hash,
        restored_file_size_bytes=staged.file_size_bytes,
        remote_etag=metadata.etag,
        rehearsal_hash=rehearsal_hash,
        request_reason=reason.strip(),
        restored_by_id=restored_by_id,
        restored_at=now,
        verified_at=now,
    )
    db.add(rehearsal)
    db.flush()
    verification = _new_verification(
        rehearsal=rehearsal,
        metadata=metadata,
        staged=staged,
        verified_by_id=restored_by_id,
        reason=reason,
        verified_at=now,
    )
    db.add(verification)
    db.flush()
    return rehearsal, verification, True


def verify_document_recovery_restore(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    verified_by_id: UUID,
    reason: str,
) -> EvidenceRecoveryRestoreVerification:
    _document, replica, snapshot, metadata, _payload = _load_verified_context(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    rehearsal = db.scalar(
        select(EvidenceRecoveryRestoreRehearsal).where(
            EvidenceRecoveryRestoreRehearsal.organization_id == organization_id,
            EvidenceRecoveryRestoreRehearsal.claim_id == claim_id,
            EvidenceRecoveryRestoreRehearsal.document_id == document_id,
            EvidenceRecoveryRestoreRehearsal.replica_id == replica.id,
        )
    )
    if rehearsal is None:
        raise RecoveryRestoreNotFound("Recovery restore rehearsal not found")
    _assert_rehearsal_lineage(rehearsal, replica=replica, snapshot=snapshot)
    staged = _verify_staging(rehearsal)
    verification = _new_verification(
        rehearsal=rehearsal,
        metadata=metadata,
        staged=staged,
        verified_by_id=verified_by_id,
        reason=reason,
        verified_at=datetime.now(UTC),
    )
    db.add(verification)
    db.flush()
    return verification


def get_document_recovery_restore_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> EvidenceRecoveryRestoreRehearsal:
    rehearsal = db.scalar(
        select(EvidenceRecoveryRestoreRehearsal).where(
            EvidenceRecoveryRestoreRehearsal.organization_id == organization_id,
            EvidenceRecoveryRestoreRehearsal.claim_id == claim_id,
            EvidenceRecoveryRestoreRehearsal.document_id == document_id,
        )
    )
    if rehearsal is None:
        raise RecoveryRestoreNotFound("Recovery restore rehearsal not found")
    return rehearsal


def list_document_recovery_restore_verifications(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> list[EvidenceRecoveryRestoreVerification]:
    rehearsal = get_document_recovery_restore_rehearsal(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryRestoreVerification)
            .where(
                EvidenceRecoveryRestoreVerification.organization_id == organization_id,
                EvidenceRecoveryRestoreVerification.claim_id == claim_id,
                EvidenceRecoveryRestoreVerification.document_id == document_id,
                EvidenceRecoveryRestoreVerification.rehearsal_id == rehearsal.id,
            )
            .order_by(EvidenceRecoveryRestoreVerification.verified_at.desc())
        )
    )
