from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_dual_write_canary_health_models import (
    EvidenceRecoveryRoutableDualWriteCanaryHealthQualification,
    EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt,
)
from app.modules.documents.recovery_routable_dual_write_canary_health_service import (
    RecoveryRoutableDualWriteCanaryHealthConflict,
    RecoveryRoutableDualWriteCanaryHealthNotFound,
    RecoveryRoutableDualWriteCanaryHealthUnavailable,
    _load_snapshot as _load_ac_snapshot,
    _matches_snapshot as _matches_ac_snapshot,
    get_routable_dual_write_canary_health_qualification,
)
from app.modules.documents.recovery_write_ownership_transition_authorization_models import (
    EvidenceRecoveryWriteOwnershipTransitionAuthorization,
    EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt,
)


WRITE_OWNERSHIP_AUTH_REVIEW_WINDOW = timedelta(minutes=10)
WRITE_OWNERSHIP_AUTH_LIFETIME = timedelta(minutes=10)


class RecoveryWriteOwnershipTransitionAuthorizationError(RuntimeError):
    pass


class RecoveryWriteOwnershipTransitionAuthorizationNotFound(RecoveryWriteOwnershipTransitionAuthorizationError):
    pass


class RecoveryWriteOwnershipTransitionAuthorizationConflict(RecoveryWriteOwnershipTransitionAuthorizationError):
    pass


class RecoveryWriteOwnershipTransitionAuthorizationUnavailable(RecoveryWriteOwnershipTransitionAuthorizationError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_ac_receipt(
    db: Session,
    *,
    q: EvidenceRecoveryRoutableDualWriteCanaryHealthQualification,
) -> EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt).where(
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.organization_id == q.organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.claim_id == q.claim_id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.document_id == q.document_id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.health_qualification_id == q.id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(
            "Qualified Phase AC artifact must have exactly one qualified receipt"
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
            receipt.local_authoritative is True,
            receipt.storage_write_performed is False,
            receipt.canary_reactivated is False,
            receipt.routable_dual_write_active is False,
            receipt.durable_write_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_put_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(
            "Phase AC qualified receipt lineage is inconsistent"
        )
    return receipt


def _fresh_ac(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
):
    try:
        q = get_routable_dual_write_canary_health_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
            for_update=True,
        )
    except RecoveryRoutableDualWriteCanaryHealthNotFound as exc:
        raise RecoveryWriteOwnershipTransitionAuthorizationNotFound(str(exc)) from exc

    if not all(
        (
            q.status == "qualified",
            q.health_state == "healthy",
            q.qualified_by_id is not None,
            q.qualified_at is not None,
            q.local_authoritative is True,
            q.storage_write_performed is False,
            q.canary_reactivated is False,
            q.routable_dual_write_active is False,
            q.durable_write_authority_created is False,
            q.read_path_switched is False,
            q.write_path_switched is False,
            q.document_storage_key_mutated is False,
            q.authoritative_storage_changed is False,
            q.destructive_action_performed is False,
            q.s3_put_performed is False,
            q.s3_copy_performed is False,
            q.s3_delete_performed is False,
            q.local_delete_performed is False,
        )
    ):
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(
            "Phase AD requires one exact qualified healthy Phase AC artifact"
        )

    receipt = _qualified_ac_receipt(db, q=q)
    try:
        snapshot = _load_ac_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=q.canary_lease_id,
        )
    except RecoveryRoutableDualWriteCanaryHealthUnavailable as exc:
        raise RecoveryWriteOwnershipTransitionAuthorizationUnavailable(str(exc)) from exc
    except RecoveryRoutableDualWriteCanaryHealthNotFound as exc:
        raise RecoveryWriteOwnershipTransitionAuthorizationNotFound(str(exc)) from exc
    except RecoveryRoutableDualWriteCanaryHealthConflict as exc:
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(str(exc)) from exc

    if not _matches_ac_snapshot(q, snapshot):
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(
            "Phase AC qualified snapshot drifted before Phase AD authorization"
        )
    return q, receipt, snapshot


def _snapshot_hash(q, receipt, snapshot) -> str:
    lease = snapshot.lease
    return _canonical_hash(
        {
            "phase_ac_health_qualification_id": str(q.id),
            "phase_ac_health_qualification_hash": q.health_qualification_hash,
            "phase_ac_health_receipt_id": str(receipt.id),
            "phase_ac_health_receipt_hash": receipt.receipt_hash,
            "phase_ac_request_snapshot_hash": q.request_snapshot_hash,
            "phase_ac_integrity_proof_hash": q.integrity_proof_hash,
            "canary_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "verification_hash": lease.verification_hash,
            "activation_receipt_hash": snapshot.activation_receipt.receipt_hash,
            "terminal_receipt_hash": snapshot.terminal_receipt.receipt_hash,
            "phase_aa_authorization_id": str(snapshot.authorization.id),
            "phase_aa_authorization_hash": snapshot.authorization.authorization_hash,
            "phase_aa_approval_receipt_hash": snapshot.approval_receipt.receipt_hash,
            "phase_z_health_qualification_hash": snapshot.phase_z.health_qualification_hash,
            "execution_hash": lease.execution_hash,
            "phase_x_authorization_hash": lease.phase_x_authorization_hash,
            "replica_hash": lease.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "canary_object_key_fingerprint": lease.canary_object_key_fingerprint,
            "observed_file_hash": snapshot.observed_file_hash,
            "observed_file_size_bytes": snapshot.observed_file_size_bytes,
            "remote_etag": snapshot.remote_etag,
            "read_route_version_at_request": snapshot.read_route.route_version,
            "write_route_version_at_request": snapshot.write_route.route_version,
            "read_route_class": snapshot.read_route.route_class,
            "read_route_authority_kind": snapshot.read_route.route_authority_kind,
            "write_mode": snapshot.write_route.write_mode,
            "active_canary_lease_id": None,
            "local_authoritative": True,
            "storage_write_performed": False,
            "write_route_lease_created": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
        }
    )


def _matches_authorization(a, q, receipt, snapshot) -> bool:
    lease = snapshot.lease
    auth = snapshot.authorization
    return all(
        (
            a.phase_ac_health_qualification_id == q.id,
            a.phase_ac_health_receipt_id == receipt.id,
            a.canary_lease_id == lease.id,
            a.phase_aa_authorization_id == auth.id,
            a.phase_aa_approval_receipt_id == snapshot.approval_receipt.id,
            a.phase_z_health_qualification_id == lease.phase_z_health_qualification_id,
            a.execution_id == lease.execution_id,
            a.phase_x_authorization_id == lease.phase_x_authorization_id,
            a.replica_id == lease.replica_id,
            a.phase_ac_health_qualification_hash == q.health_qualification_hash,
            a.phase_ac_health_receipt_hash == receipt.receipt_hash,
            a.phase_ac_request_snapshot_hash == q.request_snapshot_hash,
            a.phase_ac_integrity_proof_hash == q.integrity_proof_hash,
            a.lease_hash == lease.lease_hash,
            a.lease_snapshot_hash == lease.lease_snapshot_hash,
            a.verification_hash == lease.verification_hash,
            a.activation_receipt_hash == snapshot.activation_receipt.receipt_hash,
            a.terminal_receipt_hash == snapshot.terminal_receipt.receipt_hash,
            a.phase_aa_authorization_hash == auth.authorization_hash,
            a.phase_aa_approval_receipt_hash == snapshot.approval_receipt.receipt_hash,
            a.phase_z_health_qualification_hash == snapshot.phase_z.health_qualification_hash,
            a.execution_hash == lease.execution_hash,
            a.phase_x_authorization_hash == lease.phase_x_authorization_hash,
            a.replica_hash == lease.replica_hash,
            a.source_file_hash == lease.source_file_hash,
            a.source_file_size_bytes == lease.source_file_size_bytes,
            a.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            a.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            a.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            a.source_authority_fingerprint == lease.source_authority_fingerprint,
            a.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            a.configuration_fingerprint == lease.configuration_fingerprint,
            a.canary_object_key_fingerprint == lease.canary_object_key_fingerprint,
            a.observed_file_hash == snapshot.observed_file_hash,
            a.observed_file_size_bytes == snapshot.observed_file_size_bytes,
            a.remote_etag == snapshot.remote_etag,
            a.read_route_version_at_request == snapshot.read_route.route_version,
            a.write_route_version_at_request == snapshot.write_route.route_version,
            a.request_snapshot_hash == _snapshot_hash(q, receipt, snapshot),
            a.phase_ac_qualified_by_id == q.qualified_by_id,
            a.phase_ab_activated_by_id == q.phase_ab_activated_by_id,
            a.phase_aa_requested_by_id == q.phase_aa_requested_by_id,
            a.phase_aa_approved_by_id == q.phase_aa_approved_by_id,
            a.phase_z_qualified_by_id == q.phase_z_qualified_by_id,
            a.phase_y_executed_by_id == q.phase_y_executed_by_id,
            a.phase_x_approved_by_id == q.phase_x_approved_by_id,
        )
    )


def _receipt_hash(a, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(a.id),
            "phase_ac_health_qualification_id": str(a.phase_ac_health_qualification_id),
            "phase": phase,
            "health_state": a.health_state,
            "phase_ac_health_qualification_hash": a.phase_ac_health_qualification_hash,
            "phase_ac_health_receipt_hash": a.phase_ac_health_receipt_hash,
            "request_snapshot_hash": a.request_snapshot_hash,
            "authorization_hash": a.authorization_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_authoritative": True,
            "storage_write_performed": False,
            "write_route_lease_created": False,
            "routable_dual_write_active": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_put_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )


def _add_receipt(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt(
        organization_id=a.organization_id,
        claim_id=a.claim_id,
        document_id=a.document_id,
        authorization_id=a.id,
        phase_ac_health_qualification_id=a.phase_ac_health_qualification_id,
        phase=phase,
        health_state=a.health_state,
        phase_ac_health_qualification_hash=a.phase_ac_health_qualification_hash,
        phase_ac_health_receipt_hash=a.phase_ac_health_receipt_hash,
        request_snapshot_hash=a.request_snapshot_hash,
        authorization_hash=a.authorization_hash,
        receipt_hash=_receipt_hash(a, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        storage_write_performed=False,
        write_route_lease_created=False,
        routable_dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_recovery_write_ownership_transition_authorization(
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
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict("Phase AD request reason is required")
    current = _as_utc(now or _utc_now())
    q, ac_receipt, snapshot = _fresh_ac(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryWriteOwnershipTransitionAuthorization)
        .where(
            EvidenceRecoveryWriteOwnershipTransitionAuthorization.organization_id == organization_id,
            EvidenceRecoveryWriteOwnershipTransitionAuthorization.claim_id == claim_id,
            EvidenceRecoveryWriteOwnershipTransitionAuthorization.document_id == document_id,
            EvidenceRecoveryWriteOwnershipTransitionAuthorization.phase_ac_health_qualification_id == q.id,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
            and _matches_authorization(existing, q, ac_receipt, snapshot)
        ):
            return existing, None, "unchanged"
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(
            "Phase AD authorization already exists for this Phase AC qualification"
        )

    request_snapshot_hash = _snapshot_hash(q, ac_receipt, snapshot)
    review_expires_at = current + WRITE_OWNERSHIP_AUTH_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "request_snapshot_hash": request_snapshot_hash,
            "phase_ac_health_qualification_hash": q.health_qualification_hash,
            "phase_ac_health_receipt_hash": ac_receipt.receipt_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "max_transition_windows": 1,
            "mode": "phase_ad_authorization_only_bounded_recovery_write_ownership_transition",
        }
    )
    lease = snapshot.lease
    auth = snapshot.authorization
    a = EvidenceRecoveryWriteOwnershipTransitionAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_ac_health_qualification_id=q.id,
        phase_ac_health_receipt_id=ac_receipt.id,
        canary_lease_id=lease.id,
        phase_aa_authorization_id=auth.id,
        phase_aa_approval_receipt_id=snapshot.approval_receipt.id,
        phase_z_health_qualification_id=lease.phase_z_health_qualification_id,
        execution_id=lease.execution_id,
        phase_x_authorization_id=lease.phase_x_authorization_id,
        replica_id=lease.replica_id,
        phase_ac_health_qualification_hash=q.health_qualification_hash,
        phase_ac_health_receipt_hash=ac_receipt.receipt_hash,
        phase_ac_request_snapshot_hash=q.request_snapshot_hash,
        phase_ac_integrity_proof_hash=q.integrity_proof_hash,
        lease_hash=lease.lease_hash,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        verification_hash=lease.verification_hash,
        activation_receipt_hash=snapshot.activation_receipt.receipt_hash,
        terminal_receipt_hash=snapshot.terminal_receipt.receipt_hash,
        phase_aa_authorization_hash=auth.authorization_hash,
        phase_aa_approval_receipt_hash=snapshot.approval_receipt.receipt_hash,
        phase_z_health_qualification_hash=snapshot.phase_z.health_qualification_hash,
        execution_hash=lease.execution_hash,
        phase_x_authorization_hash=lease.phase_x_authorization_hash,
        replica_hash=lease.replica_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        local_storage_key_fingerprint=lease.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=lease.source_authority_fingerprint,
        candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
        configuration_fingerprint=lease.configuration_fingerprint,
        canary_object_key_fingerprint=lease.canary_object_key_fingerprint,
        observed_file_hash=snapshot.observed_file_hash,
        observed_file_size_bytes=snapshot.observed_file_size_bytes,
        remote_etag=snapshot.remote_etag,
        read_route_version_at_request=snapshot.read_route.route_version,
        write_route_version_at_request=snapshot.write_route.route_version,
        request_snapshot_hash=request_snapshot_hash,
        authorization_hash=authorization_hash,
        health_state="healthy",
        max_transition_windows=1,
        phase_ac_qualified_by_id=q.qualified_by_id,
        phase_ab_activated_by_id=q.phase_ab_activated_by_id,
        phase_aa_requested_by_id=q.phase_aa_requested_by_id,
        phase_aa_approved_by_id=q.phase_aa_approved_by_id,
        phase_z_qualified_by_id=q.phase_z_qualified_by_id,
        phase_y_executed_by_id=q.phase_y_executed_by_id,
        phase_x_approved_by_id=q.phase_x_approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        status="pending_second_approval",
        local_authoritative=True,
        storage_write_performed=False,
        write_route_lease_created=False,
        routable_dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(a)
    db.flush()
    auth_receipt = _add_receipt(db, a, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return a, auth_receipt, "pending_second_approval"


def get_recovery_write_ownership_transition_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryWriteOwnershipTransitionAuthorization).where(
        EvidenceRecoveryWriteOwnershipTransitionAuthorization.id == authorization_id,
        EvidenceRecoveryWriteOwnershipTransitionAuthorization.organization_id == organization_id,
        EvidenceRecoveryWriteOwnershipTransitionAuthorization.claim_id == claim_id,
        EvidenceRecoveryWriteOwnershipTransitionAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    a = db.scalar(stmt)
    if a is None:
        raise RecoveryWriteOwnershipTransitionAuthorizationNotFound(
            "Phase AD write-ownership transition authorization not found"
        )
    return a


def _terminalize(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    a.status = phase
    a.terminal_by_id = actor_id
    a.terminal_at = now
    a.terminal_reason = reason
    a.authorization_expires_at = None
    db.flush()
    return _add_receipt(db, a, phase=phase, actor_id=actor_id, reason=reason, now=now)


def approve_recovery_write_ownership_transition_authorization(
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
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict("Phase AD approval reason is required")
    current = _as_utc(now or _utc_now())
    a = get_recovery_write_ownership_transition_authorization(
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
            reason="Phase AD independent review window expired",
            now=current,
        )
        return a, receipt, "expired"
    if approved_by_id in {
        a.requested_by_id,
        a.phase_ac_qualified_by_id,
        a.phase_ab_activated_by_id,
        a.phase_aa_requested_by_id,
        a.phase_aa_approved_by_id,
        a.phase_z_qualified_by_id,
        a.phase_y_executed_by_id,
        a.phase_x_approved_by_id,
    }:
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict(
            "Phase AD approver must be independent from requester, Phase AC qualifier, Phase AB activator and prior governance actors"
        )
    try:
        q, ac_receipt, snapshot = _fresh_ac(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=a.phase_ac_health_qualification_id,
        )
    except RecoveryWriteOwnershipTransitionAuthorizationUnavailable:
        raise
    except (
        RecoveryWriteOwnershipTransitionAuthorizationNotFound,
        RecoveryWriteOwnershipTransitionAuthorizationConflict,
    ) as exc:
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason=f"Phase AD fresh verification invalidated: {exc}",
            now=current,
        )
        return a, receipt, "invalidated"
    if not _matches_authorization(a, q, ac_receipt, snapshot):
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason="Phase AD request snapshot drifted before independent approval",
            now=current,
        )
        return a, receipt, "invalidated"

    a.status = "approved"
    a.approved_by_id = approved_by_id
    a.approved_at = current
    a.authorization_expires_at = current + WRITE_OWNERSHIP_AUTH_LIFETIME
    a.approval_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, a, phase="approved", actor_id=approved_by_id, reason=normalized_reason, now=current)
    return a, receipt, "approved"


def reject_recovery_write_ownership_transition_authorization(
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
        raise RecoveryWriteOwnershipTransitionAuthorizationConflict("Phase AD rejection reason is required")
    current = _as_utc(now or _utc_now())
    a = get_recovery_write_ownership_transition_authorization(
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
            reason="Phase AD independent review window expired",
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


def list_recovery_write_ownership_transition_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
):
    get_recovery_write_ownership_transition_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt)
            .where(
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.authorization_id == authorization_id,
            )
            .order_by(
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.id.asc(),
            )
        ).all()
    )
