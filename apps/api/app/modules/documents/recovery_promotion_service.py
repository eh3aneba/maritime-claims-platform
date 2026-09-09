from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_promotion_models import EvidenceRecoveryPromotionAttestation
from app.modules.documents.recovery_restore_models import (
    EvidenceRecoveryRestoreRehearsal,
    EvidenceRecoveryRestoreVerification,
)
from app.modules.documents.recovery_restore_service import (
    RecoveryRestoreConflict,
    RecoveryRestoreNotFound,
    RecoveryRestoreUnavailable,
    _assert_rehearsal_lineage,
    _canonical_hash,
    _fingerprint,
    _load_verified_context,
    _utc_iso,
    _verify_staging,
)

PROMOTION_REVIEW_WINDOW = timedelta(hours=1)
ACTIVE_PROMOTION_STATUSES = {"pending_second_approval", "approved"}


class RecoveryPromotionError(RuntimeError):
    pass


class RecoveryPromotionNotFound(RecoveryPromotionError):
    pass


class RecoveryPromotionConflict(RecoveryPromotionError):
    pass


class RecoveryPromotionUnavailable(RecoveryPromotionError):
    pass


@dataclass(frozen=True)
class PromotionSnapshot:
    replica_id: UUID
    rehearsal_id: UUID
    restore_verification_id: UUID
    replica_hash: str
    rehearsal_hash: str
    restore_verification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    source_document_updated_at: datetime
    source_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    recovery_storage_key_fingerprint: str
    staging_storage_key_fingerprint: str
    configuration_fingerprint: str
    promotion_plan: dict
    promotion_plan_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest_restore_verification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
) -> EvidenceRecoveryRestoreVerification:
    verification = db.scalar(
        select(EvidenceRecoveryRestoreVerification)
        .where(
            EvidenceRecoveryRestoreVerification.organization_id == organization_id,
            EvidenceRecoveryRestoreVerification.claim_id == claim_id,
            EvidenceRecoveryRestoreVerification.document_id == document_id,
            EvidenceRecoveryRestoreVerification.rehearsal_id == rehearsal_id,
        )
        .order_by(
            EvidenceRecoveryRestoreVerification.verified_at.desc(),
            EvidenceRecoveryRestoreVerification.created_at.desc(),
            EvidenceRecoveryRestoreVerification.id.desc(),
        )
        .limit(1)
    )
    if verification is None:
        raise RecoveryPromotionConflict("Recovery restore rehearsal has no verification lineage")
    return verification


def _assert_verification_matches_current(
    verification: EvidenceRecoveryRestoreVerification,
    *,
    rehearsal: EvidenceRecoveryRestoreRehearsal,
    metadata,
    staged,
) -> None:
    expected = (
        verification.replica_id == rehearsal.replica_id
        and verification.rehearsal_id == rehearsal.id
        and verification.expected_file_hash == rehearsal.source_file_hash
        and verification.expected_file_size_bytes == rehearsal.source_file_size_bytes
        and verification.remote_file_hash == metadata.file_hash
        and verification.remote_file_size_bytes == metadata.file_size_bytes
        and verification.staged_file_hash == staged.file_hash
        and verification.staged_file_size_bytes == staged.file_size_bytes
        and verification.recovery_bucket_fingerprint == rehearsal.recovery_bucket_fingerprint
        and verification.staging_storage_key_fingerprint
        == rehearsal.staging_storage_key_fingerprint
    )
    if not expected:
        raise RecoveryPromotionConflict(
            "Latest recovery restore verification does not match the current recovery lineage"
        )


def _build_plan(
    *,
    document_id: UUID,
    replica_id: UUID,
    rehearsal_id: UUID,
    verification_id: UUID,
    source_file_hash: str,
    source_file_size_bytes: int,
    source_storage_key_fingerprint: str,
    replica_hash: str,
    recovery_bucket_fingerprint: str,
    recovery_storage_key_fingerprint: str,
    staging_storage_key_fingerprint: str,
    rehearsal_hash: str,
    verification_hash: str,
) -> dict:
    return {
        "contract_version": 1,
        "mode": "dry_run_only",
        "actions": [
            {
                "action_class": "verify_authoritative_source",
                "document_id": str(document_id),
                "file_hash": source_file_hash,
                "file_size_bytes": source_file_size_bytes,
                "storage_key_fingerprint": source_storage_key_fingerprint,
                "execute": False,
            },
            {
                "action_class": "verify_recovery_replica",
                "replica_id": str(replica_id),
                "replica_hash": replica_hash,
                "bucket_fingerprint": recovery_bucket_fingerprint,
                "storage_key_fingerprint": recovery_storage_key_fingerprint,
                "execute": False,
            },
            {
                "action_class": "verify_restore_staging",
                "rehearsal_id": str(rehearsal_id),
                "restore_verification_id": str(verification_id),
                "rehearsal_hash": rehearsal_hash,
                "verification_hash": verification_hash,
                "staging_storage_key_fingerprint": staging_storage_key_fingerprint,
                "execute": False,
            },
            {
                "action_class": "future_authority_switch_placeholder",
                "document_id": str(document_id),
                "source_authority_class": "local_document_storage",
                "candidate_authority_class": "verified_recovery_restore_staging",
                "execute": False,
            },
        ],
        "cutover_performed": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
    }


def _build_promotion_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> PromotionSnapshot:
    try:
        _document, replica, source, metadata, _payload = _load_verified_context(
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
            raise RecoveryPromotionNotFound("Recovery restore rehearsal not found")
        _assert_rehearsal_lineage(rehearsal, replica=replica, snapshot=source)
        staged = _verify_staging(rehearsal)
        verification = _latest_restore_verification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal.id,
        )
        _assert_verification_matches_current(
            verification,
            rehearsal=rehearsal,
            metadata=metadata,
            staged=staged,
        )
    except RecoveryPromotionError:
        raise
    except RecoveryRestoreNotFound as exc:
        raise RecoveryPromotionNotFound(str(exc)) from exc
    except RecoveryRestoreConflict as exc:
        raise RecoveryPromotionConflict(str(exc)) from exc
    except RecoveryRestoreUnavailable as exc:
        raise RecoveryPromotionUnavailable(str(exc)) from exc

    configuration_fingerprint = _canonical_hash(
        {
            "contract_version": 1,
            "promotion_mode": "dry_run_only",
            "recovery_bucket_fingerprint": rehearsal.recovery_bucket_fingerprint,
            "recovery_storage_key_fingerprint": rehearsal.recovery_storage_key_fingerprint,
            "staging_storage_key_fingerprint": rehearsal.staging_storage_key_fingerprint,
        }
    )
    plan = _build_plan(
        document_id=document_id,
        replica_id=replica.id,
        rehearsal_id=rehearsal.id,
        verification_id=verification.id,
        source_file_hash=source.file_hash,
        source_file_size_bytes=source.file_size_bytes,
        source_storage_key_fingerprint=source.storage_key_fingerprint,
        replica_hash=replica.replica_hash,
        recovery_bucket_fingerprint=replica.recovery_bucket_fingerprint,
        recovery_storage_key_fingerprint=_fingerprint(replica.recovery_storage_key),
        staging_storage_key_fingerprint=rehearsal.staging_storage_key_fingerprint,
        rehearsal_hash=rehearsal.rehearsal_hash,
        verification_hash=verification.verification_hash,
    )
    return PromotionSnapshot(
        replica_id=replica.id,
        rehearsal_id=rehearsal.id,
        restore_verification_id=verification.id,
        replica_hash=replica.replica_hash,
        rehearsal_hash=rehearsal.rehearsal_hash,
        restore_verification_hash=verification.verification_hash,
        source_file_hash=source.file_hash,
        source_file_size_bytes=source.file_size_bytes,
        source_document_updated_at=source.document_updated_at,
        source_storage_key_fingerprint=source.storage_key_fingerprint,
        recovery_bucket_fingerprint=replica.recovery_bucket_fingerprint,
        recovery_storage_key_fingerprint=_fingerprint(replica.recovery_storage_key),
        staging_storage_key_fingerprint=rehearsal.staging_storage_key_fingerprint,
        configuration_fingerprint=configuration_fingerprint,
        promotion_plan=plan,
        promotion_plan_hash=_canonical_hash(plan),
    )


def _semantic_matches(
    attestation: EvidenceRecoveryPromotionAttestation,
    snapshot: PromotionSnapshot,
) -> bool:
    return all(
        (
            attestation.replica_id == snapshot.replica_id,
            attestation.rehearsal_id == snapshot.rehearsal_id,
            attestation.restore_verification_id == snapshot.restore_verification_id,
            attestation.replica_hash == snapshot.replica_hash,
            attestation.rehearsal_hash == snapshot.rehearsal_hash,
            attestation.restore_verification_hash == snapshot.restore_verification_hash,
            attestation.source_file_hash == snapshot.source_file_hash,
            attestation.source_file_size_bytes == snapshot.source_file_size_bytes,
            _utc_iso(attestation.source_document_updated_at)
            == _utc_iso(snapshot.source_document_updated_at),
            attestation.source_storage_key_fingerprint
            == snapshot.source_storage_key_fingerprint,
            attestation.recovery_bucket_fingerprint
            == snapshot.recovery_bucket_fingerprint,
            attestation.recovery_storage_key_fingerprint
            == snapshot.recovery_storage_key_fingerprint,
            attestation.staging_storage_key_fingerprint
            == snapshot.staging_storage_key_fingerprint,
            attestation.configuration_fingerprint == snapshot.configuration_fingerprint,
            attestation.promotion_plan_hash == snapshot.promotion_plan_hash,
            attestation.promotion_plan == snapshot.promotion_plan,
        )
    )


def _get_attestation(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryPromotionAttestation:
    stmt = select(EvidenceRecoveryPromotionAttestation).where(
        EvidenceRecoveryPromotionAttestation.id == attestation_id,
        EvidenceRecoveryPromotionAttestation.organization_id == organization_id,
        EvidenceRecoveryPromotionAttestation.claim_id == claim_id,
        EvidenceRecoveryPromotionAttestation.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    attestation = db.scalar(stmt)
    if attestation is None:
        raise RecoveryPromotionNotFound("Recovery promotion attestation not found")
    return attestation


def list_recovery_promotion_attestations(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> list[EvidenceRecoveryPromotionAttestation]:
    return list(
        db.scalars(
            select(EvidenceRecoveryPromotionAttestation)
            .where(
                EvidenceRecoveryPromotionAttestation.organization_id == organization_id,
                EvidenceRecoveryPromotionAttestation.claim_id == claim_id,
                EvidenceRecoveryPromotionAttestation.document_id == document_id,
            )
            .order_by(
                EvidenceRecoveryPromotionAttestation.created_at.desc(),
                EvidenceRecoveryPromotionAttestation.id.desc(),
            )
        ).all()
    )


def get_recovery_promotion_attestation(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
) -> EvidenceRecoveryPromotionAttestation:
    return _get_attestation(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation_id,
    )


def request_recovery_promotion_attestation(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> EvidenceRecoveryPromotionAttestation:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryPromotionConflict("Recovery promotion request reason is required")
    current_time = _as_utc(now or _utc_now())

    existing = list(
        db.scalars(
            select(EvidenceRecoveryPromotionAttestation)
            .where(
                EvidenceRecoveryPromotionAttestation.organization_id == organization_id,
                EvidenceRecoveryPromotionAttestation.claim_id == claim_id,
                EvidenceRecoveryPromotionAttestation.document_id == document_id,
                EvidenceRecoveryPromotionAttestation.status.in_(ACTIVE_PROMOTION_STATUSES),
            )
            .with_for_update()
        ).all()
    )
    for item in existing:
        if _as_utc(item.attestation_expires_at) > current_time:
            raise RecoveryPromotionConflict(
                "An active recovery promotion attestation already exists for this document"
            )

    snapshot = _build_promotion_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    request_snapshot_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "replica_id": str(snapshot.replica_id),
            "rehearsal_id": str(snapshot.rehearsal_id),
            "restore_verification_id": str(snapshot.restore_verification_id),
            "replica_hash": snapshot.replica_hash,
            "rehearsal_hash": snapshot.rehearsal_hash,
            "restore_verification_hash": snapshot.restore_verification_hash,
            "source_file_hash": snapshot.source_file_hash,
            "source_file_size_bytes": snapshot.source_file_size_bytes,
            "source_document_updated_at": _utc_iso(snapshot.source_document_updated_at),
            "source_storage_key_fingerprint": snapshot.source_storage_key_fingerprint,
            "recovery_bucket_fingerprint": snapshot.recovery_bucket_fingerprint,
            "recovery_storage_key_fingerprint": snapshot.recovery_storage_key_fingerprint,
            "staging_storage_key_fingerprint": snapshot.staging_storage_key_fingerprint,
            "configuration_fingerprint": snapshot.configuration_fingerprint,
            "promotion_plan_hash": snapshot.promotion_plan_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
        }
    )
    attestation = EvidenceRecoveryPromotionAttestation(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        replica_id=snapshot.replica_id,
        rehearsal_id=snapshot.rehearsal_id,
        restore_verification_id=snapshot.restore_verification_id,
        replica_hash=snapshot.replica_hash,
        rehearsal_hash=snapshot.rehearsal_hash,
        restore_verification_hash=snapshot.restore_verification_hash,
        source_file_hash=snapshot.source_file_hash,
        source_file_size_bytes=snapshot.source_file_size_bytes,
        source_document_updated_at=snapshot.source_document_updated_at,
        source_storage_key_fingerprint=snapshot.source_storage_key_fingerprint,
        recovery_bucket_fingerprint=snapshot.recovery_bucket_fingerprint,
        recovery_storage_key_fingerprint=snapshot.recovery_storage_key_fingerprint,
        staging_storage_key_fingerprint=snapshot.staging_storage_key_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        promotion_plan=snapshot.promotion_plan,
        promotion_plan_hash=snapshot.promotion_plan_hash,
        request_snapshot_hash=request_snapshot_hash,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current_time,
        attestation_expires_at=current_time + PROMOTION_REVIEW_WINDOW,
        status="pending_second_approval",
        cutover_performed=False,
        authoritative_storage_changed=False,
    )
    db.add(attestation)
    db.flush()
    return attestation


def _terminalize(
    attestation: EvidenceRecoveryPromotionAttestation,
    *,
    actor_id: UUID,
    status: str,
    reason: str,
    now: datetime,
) -> None:
    attestation.status = status
    attestation.invalidated_by_id = actor_id
    attestation.invalidated_at = now
    attestation.decision_reason = reason


def approve_recovery_promotion_attestation(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryPromotionAttestation, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryPromotionConflict("Recovery promotion approval reason is required")
    current_time = _as_utc(now or _utc_now())
    attestation = _get_attestation(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation_id,
        for_update=True,
    )
    if attestation.status == "approved":
        return attestation, "unchanged"
    if attestation.status != "pending_second_approval":
        raise RecoveryPromotionConflict(
            f"Recovery promotion attestation is already {attestation.status}"
        )
    if attestation.requested_by_id == approved_by_id:
        raise RecoveryPromotionConflict("Four-eyes approval requires a different Admin")
    if current_time >= _as_utc(attestation.attestation_expires_at):
        _terminalize(
            attestation,
            actor_id=approved_by_id,
            status="expired",
            reason="Recovery promotion review window expired before second approval.",
            now=current_time,
        )
        db.flush()
        return attestation, "expired"

    try:
        snapshot = _build_promotion_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except (RecoveryPromotionNotFound, RecoveryPromotionConflict, RecoveryPromotionUnavailable) as exc:
        _terminalize(
            attestation,
            actor_id=approved_by_id,
            status="invalidated",
            reason=f"Recovery lineage changed or became unavailable before approval: {type(exc).__name__}",
            now=current_time,
        )
        db.flush()
        return attestation, "invalidated"

    if not _semantic_matches(attestation, snapshot):
        _terminalize(
            attestation,
            actor_id=approved_by_id,
            status="invalidated",
            reason="Recovery source, replica, restore verification, staging, or configuration drifted after request.",
            now=current_time,
        )
        db.flush()
        return attestation, "invalidated"

    attestation.status = "approved"
    attestation.approved_by_id = approved_by_id
    attestation.approved_at = current_time
    attestation.decision_reason = normalized_reason
    attestation.cutover_performed = False
    attestation.authoritative_storage_changed = False
    db.flush()
    return attestation, "approved"


def reject_recovery_promotion_attestation(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryPromotionAttestation, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryPromotionConflict("Recovery promotion rejection reason is required")
    current_time = _as_utc(now or _utc_now())
    attestation = _get_attestation(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        attestation_id=attestation_id,
        for_update=True,
    )
    if attestation.status == "rejected":
        return attestation, "unchanged"
    if attestation.status != "pending_second_approval":
        raise RecoveryPromotionConflict(
            f"Recovery promotion attestation is already {attestation.status}"
        )
    if current_time >= _as_utc(attestation.attestation_expires_at):
        _terminalize(
            attestation,
            actor_id=rejected_by_id,
            status="expired",
            reason="Recovery promotion review window expired before a decision.",
            now=current_time,
        )
        db.flush()
        return attestation, "expired"

    attestation.status = "rejected"
    attestation.rejected_by_id = rejected_by_id
    attestation.rejected_at = current_time
    attestation.decision_reason = normalized_reason
    db.flush()
    return attestation, "rejected"
