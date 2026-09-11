from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_dual_write_rehearsal_health_models import (
    EvidenceRecoveryDualWriteRehearsalHealthQualification,
    EvidenceRecoveryDualWriteRehearsalHealthReceipt,
)
from app.modules.documents.recovery_dual_write_rehearsal_health_service import (
    RecoveryDualWriteRehearsalHealthConflict,
    RecoveryDualWriteRehearsalHealthNotFound,
    RecoveryDualWriteRehearsalHealthUnavailable,
    _load_snapshot as _load_z_snapshot,
    _matches_snapshot as _matches_z_snapshot,
    get_recovery_dual_write_rehearsal_health_qualification,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_dual_write_canary_authorization_models import (
    EvidenceRecoveryRoutableDualWriteCanaryAuthorization,
    EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt,
)


CANARY_AUTH_REVIEW_WINDOW = timedelta(minutes=10)
CANARY_AUTH_LIFETIME = timedelta(minutes=10)


class RecoveryRoutableDualWriteCanaryAuthorizationError(RuntimeError):
    pass


class RecoveryRoutableDualWriteCanaryAuthorizationNotFound(RecoveryRoutableDualWriteCanaryAuthorizationError):
    pass


class RecoveryRoutableDualWriteCanaryAuthorizationConflict(RecoveryRoutableDualWriteCanaryAuthorizationError):
    pass


class RecoveryRoutableDualWriteCanaryAuthorizationUnavailable(RecoveryRoutableDualWriteCanaryAuthorizationError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_z_receipt(
    db: Session,
    *,
    q: EvidenceRecoveryDualWriteRehearsalHealthQualification,
) -> EvidenceRecoveryDualWriteRehearsalHealthReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDualWriteRehearsalHealthReceipt).where(
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.organization_id == q.organization_id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.claim_id == q.claim_id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.document_id == q.document_id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.health_qualification_id == q.id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(
            "Qualified Phase Z artifact must have exactly one qualified receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            q.status == "qualified",
            q.health_state == "healthy",
            q.qualified_by_id is not None,
            q.qualified_at is not None,
            receipt.actor_id == q.qualified_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(q.qualified_at),
            receipt.health_state == "healthy",
            receipt.integrity_proof_hash == q.integrity_proof_hash,
            receipt.request_snapshot_hash == q.request_snapshot_hash,
            receipt.health_qualification_hash == q.health_qualification_hash,
            receipt.storage_write_performed is False,
            receipt.routable_dual_write_authority_created is False,
            receipt.rehearsal_object_routable is False,
            receipt.dual_write_active is False,
            receipt.durable_write_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(
            "Phase Z qualified receipt lineage is inconsistent"
        )
    return receipt


def _fresh_z(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
):
    try:
        q = get_recovery_dual_write_rehearsal_health_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
            for_update=True,
        )
    except RecoveryDualWriteRehearsalHealthNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryAuthorizationNotFound(str(exc)) from exc
    if not all(
        (
            q.status == "qualified",
            q.health_state == "healthy",
            q.qualified_by_id is not None,
            q.qualified_at is not None,
            q.storage_write_performed is False,
            q.routable_dual_write_authority_created is False,
            q.rehearsal_object_routable is False,
            q.dual_write_active is False,
            q.durable_write_authority_created is False,
            q.read_path_switched is False,
            q.write_path_switched is False,
            q.document_storage_key_mutated is False,
            q.authoritative_storage_changed is False,
            q.destructive_action_performed is False,
            q.s3_copy_performed is False,
            q.s3_delete_performed is False,
            q.local_delete_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(
            "Phase AA requires one exact qualified healthy Phase Z artifact"
        )
    receipt = _qualified_z_receipt(db, q=q)
    try:
        snapshot = _load_z_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_id=q.execution_id,
        )
    except RecoveryDualWriteRehearsalHealthUnavailable as exc:
        raise RecoveryRoutableDualWriteCanaryAuthorizationUnavailable(str(exc)) from exc
    except RecoveryDualWriteRehearsalHealthNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryAuthorizationNotFound(str(exc)) from exc
    except RecoveryDualWriteRehearsalHealthConflict as exc:
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(str(exc)) from exc
    if not _matches_z_snapshot(q, snapshot):
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(
            "Phase Z qualified snapshot drifted before Phase AA authorization"
        )
    return q, receipt, snapshot


def _aa_snapshot_hash(q, receipt, snapshot) -> str:
    return _canonical_hash(
        {
            "phase_z_health_qualification_id": str(q.id),
            "phase_z_health_qualification_hash": q.health_qualification_hash,
            "phase_z_health_receipt_id": str(receipt.id),
            "phase_z_health_receipt_hash": receipt.receipt_hash,
            "phase_z_request_snapshot_hash": q.request_snapshot_hash,
            "phase_z_integrity_proof_hash": q.integrity_proof_hash,
            "execution_id": str(q.execution_id),
            "execution_hash": q.execution_hash,
            "verification_hash": q.verification_hash,
            "execution_receipt_hash": q.execution_receipt_hash,
            "phase_x_authorization_hash": q.phase_x_authorization_hash,
            "phase_x_approval_receipt_hash": q.phase_x_approval_receipt_hash,
            "phase_w_health_qualification_hash": q.phase_w_health_qualification_hash,
            "phase_v_transition_lease_hash": q.phase_v_transition_lease_hash,
            "phase_u_authorization_hash": q.phase_u_authorization_hash,
            "phase_t_health_qualification_hash": q.phase_t_health_qualification_hash,
            "replica_hash": q.replica_hash,
            "source_file_hash": q.source_file_hash,
            "source_file_size_bytes": q.source_file_size_bytes,
            "local_storage_key_fingerprint": q.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": q.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": q.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": q.source_authority_fingerprint,
            "candidate_authority_fingerprint": q.candidate_authority_fingerprint,
            "configuration_fingerprint": q.configuration_fingerprint,
            "route_version_at_request": snapshot.route.route_version,
            "rehearsal_object_key_fingerprint": snapshot.rehearsal_object_key_fingerprint,
            "observed_file_hash": snapshot.observed_file_hash,
            "observed_file_size_bytes": snapshot.observed_file_size_bytes,
            "remote_etag": snapshot.remote_etag,
            "health_state": "healthy",
            "storage_write_performed": False,
            "routable_dual_write_active": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
        }
    )


def _matches_authorization(a, q, receipt, snapshot) -> bool:
    return all(
        (
            a.phase_z_health_qualification_id == q.id,
            a.phase_z_health_receipt_id == receipt.id,
            a.execution_id == q.execution_id,
            a.phase_x_authorization_id == q.phase_x_authorization_id,
            a.replica_id == q.replica_id,
            a.phase_z_health_qualification_hash == q.health_qualification_hash,
            a.phase_z_request_snapshot_hash == q.request_snapshot_hash,
            a.phase_z_integrity_proof_hash == q.integrity_proof_hash,
            a.phase_z_health_receipt_hash == receipt.receipt_hash,
            a.execution_hash == q.execution_hash,
            a.verification_hash == q.verification_hash,
            a.execution_receipt_hash == q.execution_receipt_hash,
            a.phase_x_authorization_hash == q.phase_x_authorization_hash,
            a.phase_x_approval_receipt_hash == q.phase_x_approval_receipt_hash,
            a.phase_w_health_qualification_hash == q.phase_w_health_qualification_hash,
            a.phase_v_transition_lease_hash == q.phase_v_transition_lease_hash,
            a.phase_u_authorization_hash == q.phase_u_authorization_hash,
            a.phase_t_health_qualification_hash == q.phase_t_health_qualification_hash,
            a.replica_hash == q.replica_hash,
            a.source_file_hash == q.source_file_hash,
            a.source_file_size_bytes == q.source_file_size_bytes,
            a.local_storage_key_fingerprint == q.local_storage_key_fingerprint,
            a.recovery_bucket_fingerprint == q.recovery_bucket_fingerprint,
            a.candidate_storage_key_fingerprint == q.candidate_storage_key_fingerprint,
            a.source_authority_fingerprint == q.source_authority_fingerprint,
            a.candidate_authority_fingerprint == q.candidate_authority_fingerprint,
            a.configuration_fingerprint == q.configuration_fingerprint,
            a.route_version_at_request == snapshot.route.route_version,
            a.rehearsal_object_key_fingerprint == snapshot.rehearsal_object_key_fingerprint,
            a.observed_file_hash == snapshot.observed_file_hash,
            a.observed_file_size_bytes == snapshot.observed_file_size_bytes,
            a.remote_etag == snapshot.remote_etag,
            a.request_snapshot_hash == _aa_snapshot_hash(q, receipt, snapshot),
            a.phase_z_qualified_by_id == q.qualified_by_id,
            a.phase_y_executed_by_id == q.phase_y_executed_by_id,
            a.phase_x_approved_by_id == q.phase_x_approved_by_id,
        )
    )


def _receipt_hash(a, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(a.id),
            "phase_z_health_qualification_id": str(a.phase_z_health_qualification_id),
            "phase": phase,
            "health_state": a.health_state,
            "phase_z_health_qualification_hash": a.phase_z_health_qualification_hash,
            "phase_z_health_receipt_hash": a.phase_z_health_receipt_hash,
            "request_snapshot_hash": a.request_snapshot_hash,
            "authorization_hash": a.authorization_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "storage_write_performed": False,
            "canary_executed": False,
            "routable_dual_write_active": False,
            "durable_write_authority_created": False,
            "rehearsal_object_routable": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )


def _add_receipt(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt(
        organization_id=a.organization_id,
        claim_id=a.claim_id,
        document_id=a.document_id,
        authorization_id=a.id,
        phase_z_health_qualification_id=a.phase_z_health_qualification_id,
        phase=phase,
        health_state=a.health_state,
        phase_z_health_qualification_hash=a.phase_z_health_qualification_hash,
        phase_z_health_receipt_hash=a.phase_z_health_receipt_hash,
        request_snapshot_hash=a.request_snapshot_hash,
        authorization_hash=a.authorization_hash,
        receipt_hash=_receipt_hash(a, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        storage_write_performed=False,
        canary_executed=False,
        routable_dual_write_active=False,
        durable_write_authority_created=False,
        rehearsal_object_routable=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_recovery_routable_dual_write_canary_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict("Phase AA request reason is required")
    current = _as_utc(now or _utc_now())
    q, z_receipt, snapshot = _fresh_z(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryAuthorization)
        .where(
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.organization_id == organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.claim_id == claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.document_id == document_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.phase_z_health_qualification_id == q.id,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
            and _matches_authorization(existing, q, z_receipt, snapshot)
        ):
            return existing, None, "unchanged"
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(
            "Phase AA authorization already exists for this Phase Z qualification"
        )
    request_snapshot_hash = _aa_snapshot_hash(q, z_receipt, snapshot)
    review_expires_at = current + CANARY_AUTH_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "request_snapshot_hash": request_snapshot_hash,
            "phase_z_health_qualification_hash": q.health_qualification_hash,
            "phase_z_health_receipt_hash": z_receipt.receipt_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "max_canary_windows": 1,
            "mode": "phase_aa_authorization_only_one_routable_dual_write_canary",
        }
    )
    a = EvidenceRecoveryRoutableDualWriteCanaryAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_z_health_qualification_id=q.id,
        phase_z_health_receipt_id=z_receipt.id,
        execution_id=q.execution_id,
        phase_x_authorization_id=q.phase_x_authorization_id,
        replica_id=q.replica_id,
        phase_z_health_qualification_hash=q.health_qualification_hash,
        phase_z_request_snapshot_hash=q.request_snapshot_hash,
        phase_z_integrity_proof_hash=q.integrity_proof_hash,
        phase_z_health_receipt_hash=z_receipt.receipt_hash,
        execution_hash=q.execution_hash,
        verification_hash=q.verification_hash,
        execution_receipt_hash=q.execution_receipt_hash,
        phase_x_authorization_hash=q.phase_x_authorization_hash,
        phase_x_approval_receipt_hash=q.phase_x_approval_receipt_hash,
        phase_w_health_qualification_hash=q.phase_w_health_qualification_hash,
        phase_v_transition_lease_hash=q.phase_v_transition_lease_hash,
        phase_u_authorization_hash=q.phase_u_authorization_hash,
        phase_t_health_qualification_hash=q.phase_t_health_qualification_hash,
        replica_hash=q.replica_hash,
        source_file_hash=q.source_file_hash,
        source_file_size_bytes=q.source_file_size_bytes,
        local_storage_key_fingerprint=q.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=q.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=q.candidate_storage_key_fingerprint,
        source_authority_fingerprint=q.source_authority_fingerprint,
        candidate_authority_fingerprint=q.candidate_authority_fingerprint,
        configuration_fingerprint=q.configuration_fingerprint,
        route_version_at_request=snapshot.route.route_version,
        rehearsal_object_key_fingerprint=snapshot.rehearsal_object_key_fingerprint,
        observed_file_hash=snapshot.observed_file_hash,
        observed_file_size_bytes=snapshot.observed_file_size_bytes,
        remote_etag=snapshot.remote_etag,
        request_snapshot_hash=request_snapshot_hash,
        authorization_hash=authorization_hash,
        health_state="healthy",
        max_canary_windows=1,
        phase_z_qualified_by_id=q.qualified_by_id,
        phase_y_executed_by_id=q.phase_y_executed_by_id,
        phase_x_approved_by_id=q.phase_x_approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        status="pending_second_approval",
        storage_write_performed=False,
        canary_executed=False,
        routable_dual_write_active=False,
        durable_write_authority_created=False,
        rehearsal_object_routable=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(a)
    db.flush()
    receipt = _add_receipt(db, a, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return a, receipt, "pending_second_approval"


def get_recovery_routable_dual_write_canary_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryRoutableDualWriteCanaryAuthorization).where(
        EvidenceRecoveryRoutableDualWriteCanaryAuthorization.id == authorization_id,
        EvidenceRecoveryRoutableDualWriteCanaryAuthorization.organization_id == organization_id,
        EvidenceRecoveryRoutableDualWriteCanaryAuthorization.claim_id == claim_id,
        EvidenceRecoveryRoutableDualWriteCanaryAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    a = db.scalar(stmt)
    if a is None:
        raise RecoveryRoutableDualWriteCanaryAuthorizationNotFound("Phase AA canary authorization not found")
    return a


def _terminalize(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    a.status = phase
    a.terminal_by_id = actor_id
    a.terminal_at = now
    a.terminal_reason = reason
    a.authorization_expires_at = None
    db.flush()
    return _add_receipt(db, a, phase=phase, actor_id=actor_id, reason=reason, now=now)


def approve_recovery_routable_dual_write_canary_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict("Phase AA approval reason is required")
    current = _as_utc(now or _utc_now())
    a = get_recovery_routable_dual_write_canary_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if a.status != "pending_second_approval":
        return a, None, "unchanged"
    if current >= _as_utc(a.review_expires_at):
        receipt = _terminalize(
            db,
            a,
            phase="expired",
            actor_id=approved_by_id,
            reason="Phase AA independent review window expired",
            now=current,
        )
        return a, receipt, "expired"
    if approved_by_id in {
        a.requested_by_id,
        a.phase_z_qualified_by_id,
        a.phase_y_executed_by_id,
        a.phase_x_approved_by_id,
    }:
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict(
            "Phase AA approver must be independent from requester, Phase Z qualifier, Phase Y executor and Phase X approver"
        )
    try:
        q, z_receipt, snapshot = _fresh_z(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=a.phase_z_health_qualification_id,
        )
    except RecoveryRoutableDualWriteCanaryAuthorizationUnavailable:
        raise
    except (RecoveryRoutableDualWriteCanaryAuthorizationNotFound, RecoveryRoutableDualWriteCanaryAuthorizationConflict) as exc:
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason=f"Phase AA fresh verification invalidated: {exc}",
            now=current,
        )
        return a, receipt, "invalidated"
    if not _matches_authorization(a, q, z_receipt, snapshot):
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason="Phase AA request snapshot drifted before independent approval",
            now=current,
        )
        return a, receipt, "invalidated"
    a.status = "approved"
    a.approved_by_id = approved_by_id
    a.approved_at = current
    a.authorization_expires_at = current + CANARY_AUTH_LIFETIME
    a.approval_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, a, phase="approved", actor_id=approved_by_id, reason=normalized_reason, now=current)
    return a, receipt, "approved"


def reject_recovery_routable_dual_write_canary_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryAuthorizationConflict("Phase AA rejection reason is required")
    current = _as_utc(now or _utc_now())
    a = get_recovery_routable_dual_write_canary_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if a.status != "pending_second_approval":
        return a, None, "unchanged"
    if current >= _as_utc(a.review_expires_at):
        receipt = _terminalize(
            db,
            a,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase AA independent review window expired",
            now=current,
        )
        return a, receipt, "expired"
    a.status = "rejected"
    a.rejected_by_id = rejected_by_id
    a.rejected_at = current
    a.rejection_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, a, phase="rejected", actor_id=rejected_by_id, reason=normalized_reason, now=current)
    return a, receipt, "rejected"


def list_recovery_routable_dual_write_canary_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
):
    get_recovery_routable_dual_write_canary_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt)
            .where(
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.authorization_id == authorization_id,
            )
            .order_by(EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.transitioned_at.asc())
        ).all()
    )
