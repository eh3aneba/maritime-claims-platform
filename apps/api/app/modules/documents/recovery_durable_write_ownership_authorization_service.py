from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_write_ownership_authorization_models import (
    EvidenceRecoveryDurableWriteOwnershipAuthorization,
    EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_write_ownership_transition_health_models import (
    EvidenceRecoveryWriteOwnershipTransitionHealthQualification,
    EvidenceRecoveryWriteOwnershipTransitionHealthReceipt,
)
from app.modules.documents.recovery_write_ownership_transition_health_service import (
    RecoveryWriteOwnershipTransitionHealthConflict,
    RecoveryWriteOwnershipTransitionHealthNotFound,
    RecoveryWriteOwnershipTransitionHealthUnavailable,
    _load_snapshot as _load_af_snapshot,
    _matches_snapshot as _matches_af_snapshot,
    get_write_ownership_transition_health_qualification,
)


DURABLE_WRITE_AUTH_REVIEW_WINDOW = timedelta(minutes=10)
DURABLE_WRITE_AUTH_LIFETIME = timedelta(minutes=10)


class RecoveryDurableWriteOwnershipAuthorizationError(RuntimeError):
    pass


class RecoveryDurableWriteOwnershipAuthorizationNotFound(RecoveryDurableWriteOwnershipAuthorizationError):
    pass


class RecoveryDurableWriteOwnershipAuthorizationConflict(RecoveryDurableWriteOwnershipAuthorizationError):
    pass


class RecoveryDurableWriteOwnershipAuthorizationUnavailable(RecoveryDurableWriteOwnershipAuthorizationError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_af_receipt(
    db: Session,
    *,
    q: EvidenceRecoveryWriteOwnershipTransitionHealthQualification,
) -> EvidenceRecoveryWriteOwnershipTransitionHealthReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryWriteOwnershipTransitionHealthReceipt).where(
                EvidenceRecoveryWriteOwnershipTransitionHealthReceipt.organization_id == q.organization_id,
                EvidenceRecoveryWriteOwnershipTransitionHealthReceipt.claim_id == q.claim_id,
                EvidenceRecoveryWriteOwnershipTransitionHealthReceipt.document_id == q.document_id,
                EvidenceRecoveryWriteOwnershipTransitionHealthReceipt.health_qualification_id == q.id,
                EvidenceRecoveryWriteOwnershipTransitionHealthReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(
            "Qualified Phase AF artifact must have exactly one qualified receipt"
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
            receipt.write_route_reactivated is False,
            receipt.durable_write_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_put_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_overwrite_performed is False,
            receipt.local_move_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(
            "Phase AF qualified receipt lineage is inconsistent"
        )
    return receipt


def _fresh_af(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
):
    try:
        q = get_write_ownership_transition_health_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
            for_update=True,
        )
    except RecoveryWriteOwnershipTransitionHealthNotFound as exc:
        raise RecoveryDurableWriteOwnershipAuthorizationNotFound(str(exc)) from exc

    if not all(
        (
            q.status == "qualified",
            q.health_state == "healthy",
            q.qualified_by_id is not None,
            q.qualified_at is not None,
            q.local_authoritative is True,
            q.storage_write_performed is False,
            q.write_route_reactivated is False,
            q.durable_write_authority_created is False,
            q.read_path_switched is False,
            q.write_path_switched is False,
            q.document_storage_key_mutated is False,
            q.authoritative_storage_changed is False,
            q.destructive_action_performed is False,
            q.s3_put_performed is False,
            q.s3_copy_performed is False,
            q.s3_delete_performed is False,
            q.local_overwrite_performed is False,
            q.local_move_performed is False,
            q.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(
            "Phase AG requires one exact qualified healthy Phase AF artifact"
        )

    receipt = _qualified_af_receipt(db, q=q)
    try:
        snapshot = _load_af_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=q.transition_lease_id,
        )
    except RecoveryWriteOwnershipTransitionHealthUnavailable as exc:
        raise RecoveryDurableWriteOwnershipAuthorizationUnavailable(str(exc)) from exc
    except RecoveryWriteOwnershipTransitionHealthNotFound as exc:
        raise RecoveryDurableWriteOwnershipAuthorizationNotFound(str(exc)) from exc
    except RecoveryWriteOwnershipTransitionHealthConflict as exc:
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(str(exc)) from exc

    if not _matches_af_snapshot(q, snapshot):
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(
            "Phase AF qualified snapshot drifted before Phase AG authorization"
        )
    return q, receipt, snapshot


def _snapshot_hash(q, receipt, snapshot) -> str:
    lease = snapshot.lease
    ad = snapshot.authorization
    return _canonical_hash(
        {
            "phase_af_health_qualification_id": str(q.id),
            "phase_af_health_qualification_hash": q.health_qualification_hash,
            "phase_af_health_receipt_id": str(receipt.id),
            "phase_af_health_receipt_hash": receipt.receipt_hash,
            "phase_af_request_snapshot_hash": q.request_snapshot_hash,
            "phase_af_integrity_proof_hash": q.integrity_proof_hash,
            "transition_lease_id": str(lease.id),
            "transition_lease_hash": lease.lease_hash,
            "phase_ad_authorization_id": str(ad.id),
            "phase_ad_authorization_hash": ad.authorization_hash,
            "replica_id": str(lease.replica_id),
            "replica_hash": lease.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "observed_local_hash": snapshot.observed_local_hash,
            "observed_local_size_bytes": snapshot.observed_local_size_bytes,
            "observed_recovery_hash": snapshot.observed_recovery_hash,
            "observed_recovery_size_bytes": snapshot.observed_recovery_size_bytes,
            "observed_recovery_etag": snapshot.observed_recovery_etag,
            "read_route_version_at_request": snapshot.read_route.route_version,
            "write_route_version_at_request": snapshot.write_route.route_version,
            "read_route_class": snapshot.read_route.route_class,
            "read_route_authority_kind": snapshot.read_route.route_authority_kind,
            "write_mode": snapshot.write_route.write_mode,
            "active_write_ownership_transition_lease_id": None,
            "local_authoritative": True,
            "storage_write_performed": False,
            "write_route_lease_created": False,
            "write_route_reactivated": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
        }
    )


def _matches_authorization(a, q, receipt, snapshot) -> bool:
    lease = snapshot.lease
    ad = snapshot.authorization
    return all(
        (
            a.phase_af_health_qualification_id == q.id,
            a.phase_af_health_receipt_id == receipt.id,
            a.transition_lease_id == lease.id,
            a.phase_ad_authorization_id == ad.id,
            a.replica_id == lease.replica_id,
            a.phase_af_health_qualification_hash == q.health_qualification_hash,
            a.phase_af_health_receipt_hash == receipt.receipt_hash,
            a.phase_af_request_snapshot_hash == q.request_snapshot_hash,
            a.phase_af_integrity_proof_hash == q.integrity_proof_hash,
            a.transition_lease_hash == lease.lease_hash,
            a.phase_ad_authorization_hash == ad.authorization_hash,
            a.replica_hash == lease.replica_hash,
            a.source_file_hash == lease.source_file_hash,
            a.source_file_size_bytes == lease.source_file_size_bytes,
            a.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            a.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            a.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            a.source_authority_fingerprint == lease.source_authority_fingerprint,
            a.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            a.configuration_fingerprint == lease.configuration_fingerprint,
            a.observed_local_hash == snapshot.observed_local_hash,
            a.observed_local_size_bytes == snapshot.observed_local_size_bytes,
            a.observed_recovery_hash == snapshot.observed_recovery_hash,
            a.observed_recovery_size_bytes == snapshot.observed_recovery_size_bytes,
            a.observed_recovery_etag == snapshot.observed_recovery_etag,
            a.read_route_version_at_request == snapshot.read_route.route_version,
            a.write_route_version_at_request == snapshot.write_route.route_version,
            a.request_snapshot_hash == _snapshot_hash(q, receipt, snapshot),
            a.phase_af_requested_by_id == q.requested_by_id,
            a.phase_af_qualified_by_id == q.qualified_by_id,
            a.phase_ae_activated_by_id == q.phase_ae_activated_by_id,
            a.phase_ad_requested_by_id == q.phase_ad_requested_by_id,
            a.phase_ad_approved_by_id == q.phase_ad_approved_by_id,
            a.phase_ac_qualified_by_id == q.phase_ac_qualified_by_id,
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
            "phase_af_health_qualification_id": str(a.phase_af_health_qualification_id),
            "phase": phase,
            "health_state": a.health_state,
            "phase_af_health_qualification_hash": a.phase_af_health_qualification_hash,
            "phase_af_health_receipt_hash": a.phase_af_health_receipt_hash,
            "request_snapshot_hash": a.request_snapshot_hash,
            "authorization_hash": a.authorization_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_authoritative": True,
            "storage_write_performed": False,
            "write_route_lease_created": False,
            "write_route_reactivated": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_put_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_overwrite_performed": False,
            "local_move_performed": False,
            "local_delete_performed": False,
        }
    )


def _add_receipt(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt(
        organization_id=a.organization_id,
        claim_id=a.claim_id,
        document_id=a.document_id,
        authorization_id=a.id,
        phase_af_health_qualification_id=a.phase_af_health_qualification_id,
        phase=phase,
        health_state=a.health_state,
        phase_af_health_qualification_hash=a.phase_af_health_qualification_hash,
        phase_af_health_receipt_hash=a.phase_af_health_receipt_hash,
        request_snapshot_hash=a.request_snapshot_hash,
        authorization_hash=a.authorization_hash,
        receipt_hash=_receipt_hash(a, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        storage_write_performed=False,
        write_route_lease_created=False,
        write_route_reactivated=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_durable_write_ownership_authorization(
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
        raise RecoveryDurableWriteOwnershipAuthorizationConflict("Phase AG request reason is required")
    current = _as_utc(now or _utc_now())
    q, af_receipt, snapshot = _fresh_af(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableWriteOwnershipAuthorization)
        .where(
            EvidenceRecoveryDurableWriteOwnershipAuthorization.organization_id == organization_id,
            EvidenceRecoveryDurableWriteOwnershipAuthorization.claim_id == claim_id,
            EvidenceRecoveryDurableWriteOwnershipAuthorization.document_id == document_id,
            EvidenceRecoveryDurableWriteOwnershipAuthorization.phase_af_health_qualification_id == q.id,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
            and _matches_authorization(existing, q, af_receipt, snapshot)
        ):
            return existing, None, "unchanged"
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(
            "Phase AG authorization already exists for this Phase AF qualification"
        )

    request_snapshot_hash = _snapshot_hash(q, af_receipt, snapshot)
    review_expires_at = current + DURABLE_WRITE_AUTH_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "request_snapshot_hash": request_snapshot_hash,
            "phase_af_health_qualification_hash": q.health_qualification_hash,
            "phase_af_health_receipt_hash": af_receipt.receipt_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "max_execution_windows": 1,
            "mode": "phase_ag_authorization_only_durable_recovery_write_ownership",
        }
    )
    lease = snapshot.lease
    ad = snapshot.authorization
    a = EvidenceRecoveryDurableWriteOwnershipAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_af_health_qualification_id=q.id,
        phase_af_health_receipt_id=af_receipt.id,
        transition_lease_id=lease.id,
        phase_ad_authorization_id=ad.id,
        replica_id=lease.replica_id,
        phase_af_health_qualification_hash=q.health_qualification_hash,
        phase_af_health_receipt_hash=af_receipt.receipt_hash,
        phase_af_request_snapshot_hash=q.request_snapshot_hash,
        phase_af_integrity_proof_hash=q.integrity_proof_hash,
        transition_lease_hash=lease.lease_hash,
        phase_ad_authorization_hash=ad.authorization_hash,
        replica_hash=lease.replica_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        local_storage_key_fingerprint=lease.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=lease.source_authority_fingerprint,
        candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
        configuration_fingerprint=lease.configuration_fingerprint,
        observed_local_hash=snapshot.observed_local_hash,
        observed_local_size_bytes=snapshot.observed_local_size_bytes,
        observed_recovery_hash=snapshot.observed_recovery_hash,
        observed_recovery_size_bytes=snapshot.observed_recovery_size_bytes,
        observed_recovery_etag=snapshot.observed_recovery_etag,
        read_route_version_at_request=snapshot.read_route.route_version,
        write_route_version_at_request=snapshot.write_route.route_version,
        request_snapshot_hash=request_snapshot_hash,
        authorization_hash=authorization_hash,
        health_state="healthy",
        max_execution_windows=1,
        phase_af_requested_by_id=q.requested_by_id,
        phase_af_qualified_by_id=q.qualified_by_id,
        phase_ae_activated_by_id=q.phase_ae_activated_by_id,
        phase_ad_requested_by_id=q.phase_ad_requested_by_id,
        phase_ad_approved_by_id=q.phase_ad_approved_by_id,
        phase_ac_qualified_by_id=q.phase_ac_qualified_by_id,
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
        write_route_reactivated=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(a)
    db.flush()
    auth_receipt = _add_receipt(db, a, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return a, auth_receipt, "pending_second_approval"


def get_durable_write_ownership_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryDurableWriteOwnershipAuthorization).where(
        EvidenceRecoveryDurableWriteOwnershipAuthorization.id == authorization_id,
        EvidenceRecoveryDurableWriteOwnershipAuthorization.organization_id == organization_id,
        EvidenceRecoveryDurableWriteOwnershipAuthorization.claim_id == claim_id,
        EvidenceRecoveryDurableWriteOwnershipAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    a = db.scalar(stmt)
    if a is None:
        raise RecoveryDurableWriteOwnershipAuthorizationNotFound(
            "Phase AG durable write-ownership authorization not found"
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


def approve_durable_write_ownership_authorization(
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
        raise RecoveryDurableWriteOwnershipAuthorizationConflict("Phase AG approval reason is required")
    current = _as_utc(now or _utc_now())
    a = get_durable_write_ownership_authorization(
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
            reason="Phase AG independent review window expired",
            now=current,
        )
        return a, receipt, "expired"
    if approved_by_id in {
        a.requested_by_id,
        a.phase_af_requested_by_id,
        a.phase_af_qualified_by_id,
        a.phase_ae_activated_by_id,
        a.phase_ad_requested_by_id,
        a.phase_ad_approved_by_id,
        a.phase_ac_qualified_by_id,
        a.phase_ab_activated_by_id,
        a.phase_aa_requested_by_id,
        a.phase_aa_approved_by_id,
        a.phase_z_qualified_by_id,
        a.phase_y_executed_by_id,
        a.phase_x_approved_by_id,
    }:
        raise RecoveryDurableWriteOwnershipAuthorizationConflict(
            "Phase AG approver must be independent from requester, AF/AE actors and upstream governance actors"
        )
    try:
        q, af_receipt, snapshot = _fresh_af(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=a.phase_af_health_qualification_id,
        )
    except RecoveryDurableWriteOwnershipAuthorizationUnavailable:
        raise
    except (
        RecoveryDurableWriteOwnershipAuthorizationNotFound,
        RecoveryDurableWriteOwnershipAuthorizationConflict,
    ) as exc:
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason=f"Phase AG fresh verification invalidated: {exc}",
            now=current,
        )
        return a, receipt, "invalidated"
    if not _matches_authorization(a, q, af_receipt, snapshot):
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason="Phase AG request snapshot drifted before independent approval",
            now=current,
        )
        return a, receipt, "invalidated"

    a.status = "approved"
    a.approved_by_id = approved_by_id
    a.approved_at = current
    a.authorization_expires_at = current + DURABLE_WRITE_AUTH_LIFETIME
    a.approval_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, a, phase="approved", actor_id=approved_by_id, reason=normalized_reason, now=current)
    return a, receipt, "approved"


def reject_durable_write_ownership_authorization(
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
        raise RecoveryDurableWriteOwnershipAuthorizationConflict("Phase AG rejection reason is required")
    current = _as_utc(now or _utc_now())
    a = get_durable_write_ownership_authorization(
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
            reason="Phase AG independent review window expired",
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


def list_durable_write_ownership_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
):
    get_durable_write_ownership_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt)
            .where(
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.authorization_id == authorization_id,
            )
            .order_by(
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.id.asc(),
            )
        ).all()
    )
