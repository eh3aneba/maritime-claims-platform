from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.documents.recovery_promotion_models import EvidenceRecoveryPromotionAttestation
from app.modules.documents.recovery_promotion_service import (
    RecoveryPromotionConflict,
    RecoveryPromotionNotFound,
    RecoveryPromotionUnavailable,
    _as_utc,
    _build_promotion_snapshot,
    _get_attestation,
    _semantic_matches,
)
from app.modules.documents.recovery_restore_models import EvidenceRecoveryRestoreRehearsal
from app.modules.documents.recovery_restore_service import (
    RecoveryRestoreConflict,
    RecoveryRestoreNotFound,
    RecoveryRestoreUnavailable,
    _canonical_hash,
    _fingerprint,
    _fsync_directory,
    _staging_path,
    _utc_iso,
    _verify_staging,
)
from app.modules.documents.recovery_shadow_models import (
    EvidenceRecoveryShadowPromotion,
    EvidenceRecoveryShadowVerification,
)


class RecoveryShadowError(RuntimeError):
    pass


class RecoveryShadowNotFound(RecoveryShadowError):
    pass


class RecoveryShadowConflict(RecoveryShadowError):
    pass


class RecoveryShadowUnavailable(RecoveryShadowError):
    pass


@dataclass(frozen=True)
class ShadowSnapshot:
    file_hash: str
    file_size_bytes: int
    shadow_storage_key: str
    shadow_storage_key_fingerprint: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _shadow_key(attestation: EvidenceRecoveryPromotionAttestation) -> str:
    return (
        f"recovery-shadow-promotion/{attestation.organization_id}/{attestation.claim_id}/"
        f"{attestation.document_id}/{attestation.id}.candidate"
    )


def _shadow_path(storage_key: str) -> Path:
    settings = get_settings()
    root = Path(settings.local_storage_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / storage_key).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise RecoveryShadowConflict("Shadow promotion key escapes local storage root") from exc
    if not relative.parts or relative.parts[0] != "recovery-shadow-promotion":
        raise RecoveryShadowConflict("Shadow promotion target is outside the isolated namespace")
    return candidate


def _verify_payload(payload: bytes, *, expected_hash: str, expected_size: int, label: str) -> tuple[str, int]:
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_hash.lower():
        raise RecoveryShadowConflict(f"{label} hash does not match pinned evidence")
    if len(payload) != expected_size:
        raise RecoveryShadowConflict(f"{label} size does not match pinned evidence")
    return digest, len(payload)


def _verify_shadow_path(
    storage_key: str,
    *,
    expected_hash: str,
    expected_size: int,
) -> ShadowSnapshot:
    try:
        payload = _shadow_path(storage_key).read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise RecoveryShadowConflict("Shadow promotion bytes are unavailable") from exc
    digest, size = _verify_payload(
        payload,
        expected_hash=expected_hash,
        expected_size=expected_size,
        label="Shadow promotion",
    )
    return ShadowSnapshot(
        file_hash=digest,
        file_size_bytes=size,
        shadow_storage_key=storage_key,
        shadow_storage_key_fingerprint=_fingerprint(storage_key),
    )


def _write_shadow_if_absent(
    payload: bytes,
    *,
    shadow_storage_key: str,
    expected_hash: str,
    expected_size: int,
) -> ShadowSnapshot:
    _verify_payload(
        payload,
        expected_hash=expected_hash,
        expected_size=expected_size,
        label="Verified restore staging payload",
    )
    destination = _shadow_path(shadow_storage_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RecoveryShadowConflict(
            "Shadow promotion target already exists without a reusable rehearsal lineage"
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
        _verify_shadow_path_from_temp(
            temporary,
            expected_hash=expected_hash,
            expected_size=expected_size,
        )
        try:
            os.link(temporary, destination)
            linked = True
        except FileExistsError as exc:
            raise RecoveryShadowConflict("Shadow promotion target was claimed concurrently") from exc
        except OSError as exc:
            raise RecoveryShadowUnavailable(
                f"Atomic shadow promotion publish failed: {type(exc).__name__}"
            ) from exc
        _fsync_directory(destination.parent)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

    if not linked:
        raise RecoveryShadowUnavailable("Shadow promotion publish did not complete")
    return _verify_shadow_path(
        shadow_storage_key,
        expected_hash=expected_hash,
        expected_size=expected_size,
    )


def _verify_shadow_path_from_temp(path: Path, *, expected_hash: str, expected_size: int) -> None:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RecoveryShadowUnavailable("Temporary shadow promotion bytes are unavailable") from exc
    _verify_payload(
        payload,
        expected_hash=expected_hash,
        expected_size=expected_size,
        label="Temporary shadow promotion",
    )


def _assert_attestation_safety(attestation: EvidenceRecoveryPromotionAttestation) -> None:
    if attestation.cutover_performed or attestation.authoritative_storage_changed:
        raise RecoveryShadowConflict("Promotion attestation violates the non-cutover safety boundary")
    plan = attestation.promotion_plan or {}
    if plan.get("cutover_performed") is not False:
        raise RecoveryShadowConflict("Promotion plan does not explicitly prohibit cutover")
    if plan.get("authoritative_storage_changed") is not False:
        raise RecoveryShadowConflict("Promotion plan does not explicitly preserve storage authority")
    if plan.get("destructive_action_performed") is not False:
        raise RecoveryShadowConflict("Promotion plan does not explicitly prohibit destructive action")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise RecoveryShadowConflict("Promotion plan action lineage is incomplete")
    if any(not isinstance(action, dict) or action.get("execute") is not False for action in actions):
        raise RecoveryShadowConflict("Promotion plan contains executable actions")


def _load_verified_attestation_context(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    now: datetime | None = None,
    for_update: bool = False,
):
    current_time = _as_utc(now or _utc_now())
    try:
        attestation = _get_attestation(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
            for_update=for_update,
        )
        if attestation.status != "approved" or attestation.approved_by_id is None or attestation.approved_at is None:
            raise RecoveryShadowConflict("Recovery promotion attestation is not approved")
        if current_time >= _as_utc(attestation.attestation_expires_at):
            raise RecoveryShadowConflict("Recovery promotion attestation expired before shadow rehearsal")
        _assert_attestation_safety(attestation)
        snapshot = _build_promotion_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        if not _semantic_matches(attestation, snapshot):
            raise RecoveryShadowConflict("Recovery promotion lineage drifted after approval")
        rehearsal = db.scalar(
            select(EvidenceRecoveryRestoreRehearsal).where(
                EvidenceRecoveryRestoreRehearsal.id == attestation.rehearsal_id,
                EvidenceRecoveryRestoreRehearsal.organization_id == organization_id,
                EvidenceRecoveryRestoreRehearsal.claim_id == claim_id,
                EvidenceRecoveryRestoreRehearsal.document_id == document_id,
                EvidenceRecoveryRestoreRehearsal.replica_id == attestation.replica_id,
            )
        )
        if rehearsal is None:
            raise RecoveryShadowNotFound("Recovery restore rehearsal not found")
        staged = _verify_staging(rehearsal)
        payload = _staging_path(staged.staging_storage_key).read_bytes()
        _verify_payload(
            payload,
            expected_hash=attestation.source_file_hash,
            expected_size=attestation.source_file_size_bytes,
            label="Restore staging candidate",
        )
        return attestation, snapshot, rehearsal, staged, payload
    except RecoveryShadowError:
        raise
    except RecoveryPromotionNotFound as exc:
        raise RecoveryShadowNotFound(str(exc)) from exc
    except RecoveryPromotionConflict as exc:
        raise RecoveryShadowConflict(str(exc)) from exc
    except RecoveryPromotionUnavailable as exc:
        raise RecoveryShadowUnavailable(str(exc)) from exc
    except RecoveryRestoreNotFound as exc:
        raise RecoveryShadowNotFound(str(exc)) from exc
    except RecoveryRestoreConflict as exc:
        raise RecoveryShadowConflict(str(exc)) from exc
    except RecoveryRestoreUnavailable as exc:
        raise RecoveryShadowUnavailable(str(exc)) from exc
    except OSError as exc:
        raise RecoveryShadowUnavailable("Restore staging candidate could not be read") from exc


def _assert_shadow_lineage(
    shadow: EvidenceRecoveryShadowPromotion,
    *,
    attestation: EvidenceRecoveryPromotionAttestation,
) -> None:
    expected_key = _shadow_key(attestation)
    expected = all(
        (
            shadow.organization_id == attestation.organization_id,
            shadow.claim_id == attestation.claim_id,
            shadow.document_id == attestation.document_id,
            shadow.attestation_id == attestation.id,
            shadow.replica_id == attestation.replica_id,
            shadow.rehearsal_id == attestation.rehearsal_id,
            shadow.restore_verification_id == attestation.restore_verification_id,
            shadow.attestation_request_snapshot_hash == attestation.request_snapshot_hash,
            shadow.promotion_plan_hash == attestation.promotion_plan_hash,
            shadow.configuration_fingerprint == attestation.configuration_fingerprint,
            shadow.replica_hash == attestation.replica_hash,
            shadow.rehearsal_hash == attestation.rehearsal_hash,
            shadow.restore_verification_hash == attestation.restore_verification_hash,
            shadow.source_file_hash == attestation.source_file_hash,
            shadow.source_file_size_bytes == attestation.source_file_size_bytes,
            _utc_iso(shadow.source_document_updated_at) == _utc_iso(attestation.source_document_updated_at),
            shadow.source_storage_key_fingerprint == attestation.source_storage_key_fingerprint,
            shadow.recovery_bucket_fingerprint == attestation.recovery_bucket_fingerprint,
            shadow.recovery_storage_key_fingerprint == attestation.recovery_storage_key_fingerprint,
            shadow.staging_storage_key_fingerprint == attestation.staging_storage_key_fingerprint,
            shadow.shadow_storage_key == expected_key,
            shadow.shadow_storage_key_fingerprint == _fingerprint(expected_key),
            shadow.shadow_file_hash == attestation.source_file_hash,
            shadow.shadow_file_size_bytes == attestation.source_file_size_bytes,
        )
    )
    if not expected:
        raise RecoveryShadowConflict("Shadow promotion rehearsal lineage drifted from approved attestation")


def _new_verification(
    *,
    shadow: EvidenceRecoveryShadowPromotion,
    verified: ShadowSnapshot,
    verified_by_id: UUID,
    reason: str,
    verified_at: datetime,
) -> EvidenceRecoveryShadowVerification:
    verification_hash = _canonical_hash(
        {
            "shadow_promotion_id": str(shadow.id),
            "attestation_id": str(shadow.attestation_id),
            "document_id": str(shadow.document_id),
            "expected_file_hash": shadow.source_file_hash,
            "expected_file_size_bytes": shadow.source_file_size_bytes,
            "shadow_file_hash": verified.file_hash,
            "shadow_file_size_bytes": verified.file_size_bytes,
            "promotion_plan_hash": shadow.promotion_plan_hash,
            "configuration_fingerprint": shadow.configuration_fingerprint,
            "shadow_storage_key_fingerprint": verified.shadow_storage_key_fingerprint,
            "verified_by_id": str(verified_by_id),
            "verified_at": _utc_iso(verified_at),
            "reason": reason.strip(),
        }
    )
    return EvidenceRecoveryShadowVerification(
        organization_id=shadow.organization_id,
        claim_id=shadow.claim_id,
        document_id=shadow.document_id,
        attestation_id=shadow.attestation_id,
        shadow_promotion_id=shadow.id,
        expected_file_hash=shadow.source_file_hash,
        expected_file_size_bytes=shadow.source_file_size_bytes,
        shadow_file_hash=verified.file_hash,
        shadow_file_size_bytes=verified.file_size_bytes,
        promotion_plan_hash=shadow.promotion_plan_hash,
        configuration_fingerprint=shadow.configuration_fingerprint,
        shadow_storage_key_fingerprint=verified.shadow_storage_key_fingerprint,
        verification_reason=reason.strip(),
        verification_hash=verification_hash,
        verified_by_id=verified_by_id,
        verified_at=verified_at,
    )


def rehearse_recovery_shadow_promotion(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    promoted_by_id: UUID,
    reason: str,
) -> tuple[EvidenceRecoveryShadowPromotion, EvidenceRecoveryShadowVerification, bool]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryShadowConflict("Shadow promotion rehearsal reason is required")
    attestation, _snapshot, _rehearsal, _staged, payload = _load_verified_attestation_context(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation_id,
        for_update=True,
    )
    existing = db.scalar(
        select(EvidenceRecoveryShadowPromotion).where(
            EvidenceRecoveryShadowPromotion.organization_id == organization_id,
            EvidenceRecoveryShadowPromotion.claim_id == claim_id,
            EvidenceRecoveryShadowPromotion.document_id == document_id,
            EvidenceRecoveryShadowPromotion.attestation_id == attestation_id,
        )
    )
    now = _utc_now()
    if existing is not None:
        _assert_shadow_lineage(existing, attestation=attestation)
        verified = _verify_shadow_path(
            existing.shadow_storage_key,
            expected_hash=existing.source_file_hash,
            expected_size=existing.source_file_size_bytes,
        )
        verification = _new_verification(
            shadow=existing,
            verified=verified,
            verified_by_id=promoted_by_id,
            reason=normalized_reason,
            verified_at=now,
        )
        db.add(verification)
        db.flush()
        return existing, verification, False

    shadow_key = _shadow_key(attestation)
    verified = _write_shadow_if_absent(
        payload,
        shadow_storage_key=shadow_key,
        expected_hash=attestation.source_file_hash,
        expected_size=attestation.source_file_size_bytes,
    )
    shadow_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "attestation_id": str(attestation.id),
            "attestation_request_snapshot_hash": attestation.request_snapshot_hash,
            "promotion_plan_hash": attestation.promotion_plan_hash,
            "configuration_fingerprint": attestation.configuration_fingerprint,
            "replica_id": str(attestation.replica_id),
            "rehearsal_id": str(attestation.rehearsal_id),
            "restore_verification_id": str(attestation.restore_verification_id),
            "source_file_hash": attestation.source_file_hash,
            "source_file_size_bytes": attestation.source_file_size_bytes,
            "shadow_storage_key_fingerprint": verified.shadow_storage_key_fingerprint,
            "shadow_file_hash": verified.file_hash,
            "shadow_file_size_bytes": verified.file_size_bytes,
            "promoted_by_id": str(promoted_by_id),
            "promoted_at": _utc_iso(now),
        }
    )
    shadow = EvidenceRecoveryShadowPromotion(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation.id,
        replica_id=attestation.replica_id,
        rehearsal_id=attestation.rehearsal_id,
        restore_verification_id=attestation.restore_verification_id,
        attestation_request_snapshot_hash=attestation.request_snapshot_hash,
        promotion_plan_hash=attestation.promotion_plan_hash,
        configuration_fingerprint=attestation.configuration_fingerprint,
        replica_hash=attestation.replica_hash,
        rehearsal_hash=attestation.rehearsal_hash,
        restore_verification_hash=attestation.restore_verification_hash,
        source_file_hash=attestation.source_file_hash,
        source_file_size_bytes=attestation.source_file_size_bytes,
        source_document_updated_at=attestation.source_document_updated_at,
        source_storage_key_fingerprint=attestation.source_storage_key_fingerprint,
        recovery_bucket_fingerprint=attestation.recovery_bucket_fingerprint,
        recovery_storage_key_fingerprint=attestation.recovery_storage_key_fingerprint,
        staging_storage_key_fingerprint=attestation.staging_storage_key_fingerprint,
        shadow_storage_key=verified.shadow_storage_key,
        shadow_storage_key_fingerprint=verified.shadow_storage_key_fingerprint,
        shadow_file_hash=verified.file_hash,
        shadow_file_size_bytes=verified.file_size_bytes,
        shadow_promotion_hash=shadow_hash,
        rehearsal_reason=normalized_reason,
        promoted_by_id=promoted_by_id,
        promoted_at=now,
        verified_at=now,
    )
    db.add(shadow)
    db.flush()
    verification = _new_verification(
        shadow=shadow,
        verified=verified,
        verified_by_id=promoted_by_id,
        reason=normalized_reason,
        verified_at=now,
    )
    db.add(verification)
    db.flush()
    return shadow, verification, True


def verify_recovery_shadow_promotion(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    verified_by_id: UUID,
    reason: str,
) -> EvidenceRecoveryShadowVerification:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryShadowConflict("Shadow promotion verification reason is required")
    attestation, _snapshot, _rehearsal, _staged, _payload = _load_verified_attestation_context(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation_id,
    )
    shadow = db.scalar(
        select(EvidenceRecoveryShadowPromotion).where(
            EvidenceRecoveryShadowPromotion.organization_id == organization_id,
            EvidenceRecoveryShadowPromotion.claim_id == claim_id,
            EvidenceRecoveryShadowPromotion.document_id == document_id,
            EvidenceRecoveryShadowPromotion.attestation_id == attestation_id,
        )
    )
    if shadow is None:
        raise RecoveryShadowNotFound("Shadow promotion rehearsal not found")
    _assert_shadow_lineage(shadow, attestation=attestation)
    verified = _verify_shadow_path(
        shadow.shadow_storage_key,
        expected_hash=shadow.source_file_hash,
        expected_size=shadow.source_file_size_bytes,
    )
    verification = _new_verification(
        shadow=shadow,
        verified=verified,
        verified_by_id=verified_by_id,
        reason=normalized_reason,
        verified_at=_utc_now(),
    )
    db.add(verification)
    db.flush()
    return verification


def get_recovery_shadow_promotion(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
) -> EvidenceRecoveryShadowPromotion:
    shadow = db.scalar(
        select(EvidenceRecoveryShadowPromotion).where(
            EvidenceRecoveryShadowPromotion.organization_id == organization_id,
            EvidenceRecoveryShadowPromotion.claim_id == claim_id,
            EvidenceRecoveryShadowPromotion.document_id == document_id,
            EvidenceRecoveryShadowPromotion.attestation_id == attestation_id,
        )
    )
    if shadow is None:
        raise RecoveryShadowNotFound("Shadow promotion rehearsal not found")
    return shadow


def list_recovery_shadow_verifications(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
) -> list[EvidenceRecoveryShadowVerification]:
    shadow = get_recovery_shadow_promotion(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryShadowVerification)
            .where(
                EvidenceRecoveryShadowVerification.organization_id == organization_id,
                EvidenceRecoveryShadowVerification.claim_id == claim_id,
                EvidenceRecoveryShadowVerification.document_id == document_id,
                EvidenceRecoveryShadowVerification.attestation_id == attestation_id,
                EvidenceRecoveryShadowVerification.shadow_promotion_id == shadow.id,
            )
            .order_by(
                EvidenceRecoveryShadowVerification.verified_at.desc(),
                EvidenceRecoveryShadowVerification.created_at.desc(),
            )
        ).all()
    )
