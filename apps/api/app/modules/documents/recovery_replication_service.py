from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.documents.models import Document
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    S3CompatibleEvidenceStore,
    S3ObjectStoreConfig,
)
from app.modules.documents.recovery_replication_models import (
    EvidenceRecoveryReplica,
    EvidenceRecoveryVerification,
)
from app.modules.documents.storage import LocalDocumentStorage


class RecoveryReplicationError(RuntimeError):
    pass


class RecoveryReplicationNotFound(RecoveryReplicationError):
    pass


class RecoveryReplicationConflict(RecoveryReplicationError):
    pass


class RecoveryReplicationUnavailable(RecoveryReplicationError):
    pass


@dataclass(frozen=True)
class LocalEvidenceSnapshot:
    payload: bytes
    file_hash: str
    file_size_bytes: int
    document_updated_at: datetime
    storage_key_fingerprint: str
    recovery_storage_key: str


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _suffix_for_document(document: Document) -> str:
    suffix = Path(document.filename).suffix.lower().strip()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return ".bin"
    return suffix


def _recovery_key(document: Document) -> str:
    return (
        f"recovery/evidence/{document.organization_id}/{document.claim_id}/"
        f"{document.id}{_suffix_for_document(document)}"
    )


def _build_store() -> S3CompatibleEvidenceStore:
    settings = get_settings()
    if settings.storage_backend.lower().strip() != "local":
        raise RecoveryReplicationUnavailable(
            "Recovery replication requires local evidence to remain authoritative"
        )
    if not settings.s3_foundation_enabled:
        raise RecoveryReplicationUnavailable(
            "S3-compatible recovery foundation is not enabled"
        )
    config = S3ObjectStoreConfig(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        session_token=settings.s3_session_token.get_secret_value(),
        request_timeout_seconds=settings.s3_request_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
        tls_verify=settings.s3_tls_verify,
    )
    strict = settings.app_env.lower().strip() in {"staging", "production"}
    try:
        config.validate(require_https=strict)
    except ObjectStorageError as exc:
        raise RecoveryReplicationUnavailable(str(exc)) from exc
    if strict and not config.tls_verify:
        raise RecoveryReplicationUnavailable(
            "S3 TLS verification must be enabled in staging/production"
        )
    return S3CompatibleEvidenceStore(config)


def _load_document_for_update(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> Document:
    document = db.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
            Document.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if document is None:
        raise RecoveryReplicationNotFound("Document not found")
    return document


def _snapshot_local(document: Document) -> LocalEvidenceSnapshot:
    settings = get_settings()
    storage = LocalDocumentStorage(
        settings.local_storage_path,
        max_upload_bytes=settings.max_upload_bytes,
    )
    try:
        path = storage.path_for(document.storage_key)
        payload = path.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise RecoveryReplicationConflict(
            "Authoritative local evidence bytes are unavailable"
        ) from exc

    digest = hashlib.sha256(payload).hexdigest()
    if digest != document.file_hash.lower():
        raise RecoveryReplicationConflict(
            "Authoritative local evidence hash drifted from Document metadata"
        )
    if len(payload) != document.file_size_bytes:
        raise RecoveryReplicationConflict(
            "Authoritative local evidence size drifted from Document metadata"
        )
    return LocalEvidenceSnapshot(
        payload=payload,
        file_hash=digest,
        file_size_bytes=len(payload),
        document_updated_at=document.updated_at,
        storage_key_fingerprint=hashlib.sha256(
            document.storage_key.encode("utf-8")
        ).hexdigest(),
        recovery_storage_key=_recovery_key(document),
    )


def _assert_replica_matches_source(
    replica: EvidenceRecoveryReplica,
    snapshot: LocalEvidenceSnapshot,
) -> None:
    expected = (
        replica.source_file_hash == snapshot.file_hash
        and replica.source_file_size_bytes == snapshot.file_size_bytes
        and replica.source_storage_key_fingerprint == snapshot.storage_key_fingerprint
        and _utc_iso(replica.source_document_updated_at)
        == _utc_iso(snapshot.document_updated_at)
        and replica.recovery_storage_key == snapshot.recovery_storage_key
    )
    if not expected:
        raise RecoveryReplicationConflict(
            "Local evidence changed after the verified recovery replica was pinned"
        )


def _verify_remote(
    store: S3CompatibleEvidenceStore,
    *,
    storage_key: str,
    expected_hash: str,
    expected_size: int,
):
    try:
        metadata = store.head_object(storage_key=storage_key)
        if metadata.file_hash != expected_hash or metadata.file_size_bytes != expected_size:
            raise RecoveryReplicationConflict(
                "Recovery object metadata does not match authoritative evidence"
            )
        payload = store.get_bytes(
            storage_key=storage_key,
            expected_sha256=expected_hash,
        )
    except ObjectStorageNotFound as exc:
        raise RecoveryReplicationConflict("Recovery object is missing") from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryReplicationConflict(
            "Recovery object failed integrity verification"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryReplicationUnavailable(
            "Recovery storage verification is unavailable"
        ) from exc
    if len(payload) != expected_size:
        raise RecoveryReplicationConflict(
            "Recovery object byte length does not match authoritative evidence"
        )
    return metadata


def _ensure_remote_replica(
    store: S3CompatibleEvidenceStore,
    snapshot: LocalEvidenceSnapshot,
):
    # The locked Document row serializes application replication attempts. Existing
    # remote data is never knowingly overwritten: a present object must match first.
    try:
        metadata = store.head_object(storage_key=snapshot.recovery_storage_key)
    except ObjectStorageNotFound:
        try:
            store.put_bytes(
                snapshot.payload,
                storage_key=snapshot.recovery_storage_key,
                expected_sha256=snapshot.file_hash,
            )
        except ObjectStorageError as exc:
            raise RecoveryReplicationUnavailable(
                "Recovery storage upload is unavailable"
            ) from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryReplicationConflict(
            "Existing recovery object has invalid integrity metadata"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryReplicationUnavailable(
            "Recovery storage lookup is unavailable"
        ) from exc
    else:
        if (
            metadata.file_hash != snapshot.file_hash
            or metadata.file_size_bytes != snapshot.file_size_bytes
        ):
            raise RecoveryReplicationConflict(
                "Existing recovery object conflicts with authoritative evidence"
            )

    return _verify_remote(
        store,
        storage_key=snapshot.recovery_storage_key,
        expected_hash=snapshot.file_hash,
        expected_size=snapshot.file_size_bytes,
    )


def _new_verification(
    *,
    replica: EvidenceRecoveryReplica,
    metadata,
    verified_by_id: UUID,
    reason: str,
    verified_at: datetime,
) -> EvidenceRecoveryVerification:
    verification_hash = _canonical_hash(
        {
            "replica_id": str(replica.id),
            "document_id": str(replica.document_id),
            "expected_file_hash": replica.source_file_hash,
            "expected_file_size_bytes": replica.source_file_size_bytes,
            "observed_file_hash": metadata.file_hash,
            "observed_file_size_bytes": metadata.file_size_bytes,
            "recovery_bucket_fingerprint": replica.recovery_bucket_fingerprint,
            "remote_etag": metadata.etag,
            "verified_by_id": str(verified_by_id),
            "verified_at": _utc_iso(verified_at),
            "reason": reason.strip(),
        }
    )
    return EvidenceRecoveryVerification(
        organization_id=replica.organization_id,
        claim_id=replica.claim_id,
        document_id=replica.document_id,
        replica_id=replica.id,
        expected_file_hash=replica.source_file_hash,
        expected_file_size_bytes=replica.source_file_size_bytes,
        observed_file_hash=metadata.file_hash,
        observed_file_size_bytes=metadata.file_size_bytes,
        recovery_bucket_fingerprint=replica.recovery_bucket_fingerprint,
        remote_etag=metadata.etag,
        verification_reason=reason.strip(),
        verification_hash=verification_hash,
        verified_by_id=verified_by_id,
        verified_at=verified_at,
    )


def replicate_document_for_recovery(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    replicated_by_id: UUID,
    reason: str,
) -> tuple[EvidenceRecoveryReplica, EvidenceRecoveryVerification, bool]:
    document = _load_document_for_update(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    snapshot = _snapshot_local(document)
    store = _build_store()
    bucket_fingerprint = store.sanitized_health_identity.bucket_fingerprint

    existing = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.organization_id == organization_id,
            EvidenceRecoveryReplica.claim_id == claim_id,
            EvidenceRecoveryReplica.document_id == document_id,
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        _assert_replica_matches_source(existing, snapshot)
        if existing.recovery_bucket_fingerprint != bucket_fingerprint:
            raise RecoveryReplicationConflict(
                "Configured recovery bucket changed after replica lineage was pinned"
            )
        metadata = _verify_remote(
            store,
            storage_key=existing.recovery_storage_key,
            expected_hash=existing.source_file_hash,
            expected_size=existing.source_file_size_bytes,
        )
        verification = _new_verification(
            replica=existing,
            metadata=metadata,
            verified_by_id=replicated_by_id,
            reason=reason,
            verified_at=now,
        )
        db.add(verification)
        db.flush()
        return existing, verification, False

    metadata = _ensure_remote_replica(store, snapshot)
    replica_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "source_file_hash": snapshot.file_hash,
            "source_file_size_bytes": snapshot.file_size_bytes,
            "source_document_updated_at": _utc_iso(snapshot.document_updated_at),
            "source_storage_key_fingerprint": snapshot.storage_key_fingerprint,
            "recovery_storage_key": snapshot.recovery_storage_key,
            "recovery_bucket_fingerprint": bucket_fingerprint,
        }
    )
    replica = EvidenceRecoveryReplica(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        source_file_hash=snapshot.file_hash,
        source_file_size_bytes=snapshot.file_size_bytes,
        source_document_updated_at=snapshot.document_updated_at,
        source_storage_key_fingerprint=snapshot.storage_key_fingerprint,
        recovery_storage_key=snapshot.recovery_storage_key,
        recovery_bucket_fingerprint=bucket_fingerprint,
        remote_etag=metadata.etag,
        replica_hash=replica_hash,
        request_reason=reason.strip(),
        replicated_by_id=replicated_by_id,
        replicated_at=now,
        verified_at=now,
    )
    db.add(replica)
    db.flush()
    verification = _new_verification(
        replica=replica,
        metadata=metadata,
        verified_by_id=replicated_by_id,
        reason=reason,
        verified_at=now,
    )
    db.add(verification)
    db.flush()
    return replica, verification, True


def verify_document_recovery_replica(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    verified_by_id: UUID,
    reason: str,
) -> EvidenceRecoveryVerification:
    document = _load_document_for_update(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.organization_id == organization_id,
            EvidenceRecoveryReplica.claim_id == claim_id,
            EvidenceRecoveryReplica.document_id == document_id,
        )
    )
    if replica is None:
        raise RecoveryReplicationNotFound("Recovery replica not found")
    snapshot = _snapshot_local(document)
    _assert_replica_matches_source(replica, snapshot)
    store = _build_store()
    if (
        replica.recovery_bucket_fingerprint
        != store.sanitized_health_identity.bucket_fingerprint
    ):
        raise RecoveryReplicationConflict(
            "Configured recovery bucket changed after replica lineage was pinned"
        )
    metadata = _verify_remote(
        store,
        storage_key=replica.recovery_storage_key,
        expected_hash=replica.source_file_hash,
        expected_size=replica.source_file_size_bytes,
    )
    verification = _new_verification(
        replica=replica,
        metadata=metadata,
        verified_by_id=verified_by_id,
        reason=reason,
        verified_at=datetime.now(UTC),
    )
    db.add(verification)
    db.flush()
    return verification


def get_document_recovery_replica(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> EvidenceRecoveryReplica:
    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.organization_id == organization_id,
            EvidenceRecoveryReplica.claim_id == claim_id,
            EvidenceRecoveryReplica.document_id == document_id,
        )
    )
    if replica is None:
        raise RecoveryReplicationNotFound("Recovery replica not found")
    return replica


def list_document_recovery_verifications(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> list[EvidenceRecoveryVerification]:
    replica = get_document_recovery_replica(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryVerification)
            .where(
                EvidenceRecoveryVerification.organization_id == organization_id,
                EvidenceRecoveryVerification.claim_id == claim_id,
                EvidenceRecoveryVerification.document_id == document_id,
                EvidenceRecoveryVerification.replica_id == replica.id,
            )
            .order_by(EvidenceRecoveryVerification.verified_at.desc())
        )
    )
