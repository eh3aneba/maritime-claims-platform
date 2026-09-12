from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authoritative_storage_ownership_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization,
    EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt,
)
from app.modules.documents.recovery_durable_write_ownership_health_models import (
    EvidenceRecoveryDurableWriteOwnershipHealthQualification,
    EvidenceRecoveryDurableWriteOwnershipHealthReceipt,
)
from app.modules.documents.recovery_durable_write_ownership_health_service import (
    RecoveryDurableWriteOwnershipHealthConflict,
    RecoveryDurableWriteOwnershipHealthNotFound,
    RecoveryDurableWriteOwnershipHealthUnavailable,
    _active_ah_snapshot,
    _matches_snapshot,
    get_durable_write_ownership_health_qualification,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


AUTHORITATIVE_STORAGE_AUTH_REVIEW_WINDOW = timedelta(minutes=10)
AUTHORITATIVE_STORAGE_AUTH_LIFETIME = timedelta(minutes=10)


class RecoveryAuthoritativeStorageOwnershipAuthorizationError(RuntimeError):
    pass


class RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound(
    RecoveryAuthoritativeStorageOwnershipAuthorizationError
):
    pass


class RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
    RecoveryAuthoritativeStorageOwnershipAuthorizationError
):
    pass


class RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable(
    RecoveryAuthoritativeStorageOwnershipAuthorizationError
):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_ai_receipt(
    db: Session,
    *,
    q: EvidenceRecoveryDurableWriteOwnershipHealthQualification,
) -> EvidenceRecoveryDurableWriteOwnershipHealthReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipHealthReceipt).where(
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.organization_id == q.organization_id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.claim_id == q.claim_id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.document_id == q.document_id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.health_qualification_id == q.id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Qualified Phase AI artifact must have exactly one qualified receipt"
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
            receipt.observed_durable_write_mode == "recovery_primary",
            receipt.observed_durable_write_ownership_active is True,
            receipt.integrity_proof_hash == q.integrity_proof_hash,
            receipt.request_snapshot_hash == q.request_snapshot_hash,
            receipt.health_qualification_hash == q.health_qualification_hash,
            receipt.local_authoritative is True,
            receipt.storage_write_performed is False,
            receipt.route_mutation_performed is False,
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
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Phase AI qualified receipt lineage is inconsistent"
        )
    return receipt


def _fresh_ai(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
):
    try:
        q = get_durable_write_ownership_health_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=health_qualification_id,
            for_update=True,
        )
    except RecoveryDurableWriteOwnershipHealthNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound(str(exc)) from exc

    if not all(
        (
            q.status == "qualified",
            q.health_state == "healthy",
            q.qualified_by_id is not None,
            q.qualified_at is not None,
            q.observed_durable_write_mode == "recovery_primary",
            q.observed_durable_write_ownership_active is True,
            q.local_authoritative is True,
            q.storage_write_performed is False,
            q.route_mutation_performed is False,
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
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Phase AJ requires one exact qualified healthy Phase AI artifact"
        )

    receipt = _qualified_ai_receipt(db, q=q)
    try:
        snapshot = _active_ah_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=q.durable_write_ownership_lease_id,
        )
    except RecoveryDurableWriteOwnershipHealthUnavailable as exc:
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable(str(exc)) from exc
    except RecoveryDurableWriteOwnershipHealthNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound(str(exc)) from exc
    except RecoveryDurableWriteOwnershipHealthConflict as exc:
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(str(exc)) from exc

    if not _matches_snapshot(q, snapshot):
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Phase AI qualified snapshot drifted before Phase AJ authorization"
        )
    return q, receipt, snapshot


def _snapshot_hash(q, receipt, snapshot) -> str:
    lease = snapshot.lease
    af = snapshot.phase_af_snapshot
    return _canonical_hash(
        {
            "phase_ai_health_qualification_id": str(q.id),
            "phase_ai_health_qualification_hash": q.health_qualification_hash,
            "phase_ai_health_receipt_id": str(receipt.id),
            "phase_ai_health_receipt_hash": receipt.receipt_hash,
            "phase_ai_request_snapshot_hash": q.request_snapshot_hash,
            "phase_ai_integrity_proof_hash": q.integrity_proof_hash,
            "durable_write_ownership_lease_id": str(lease.id),
            "durable_write_ownership_lease_hash": lease.lease_hash,
            "phase_ag_authorization_id": str(snapshot.authorization.id),
            "phase_ag_authorization_hash": snapshot.authorization.authorization_hash,
            "replica_id": str(af.replica.id),
            "replica_hash": af.replica.replica_hash,
            "source_file_hash": q.source_file_hash,
            "source_file_size_bytes": q.source_file_size_bytes,
            "local_storage_key_fingerprint": q.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": q.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": q.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": q.source_authority_fingerprint,
            "candidate_authority_fingerprint": q.candidate_authority_fingerprint,
            "configuration_fingerprint": q.configuration_fingerprint,
            "observed_local_hash": q.observed_local_hash,
            "observed_local_size_bytes": q.observed_local_size_bytes,
            "observed_recovery_hash": q.observed_recovery_hash,
            "observed_recovery_size_bytes": q.observed_recovery_size_bytes,
            "observed_recovery_etag": q.observed_recovery_etag,
            "read_route_version_at_request": q.read_route_version_at_request,
            "experimental_write_route_version_at_request": q.experimental_write_route_version_at_request,
            "durable_route_version_at_request": q.durable_route_version_at_request,
            "observed_durable_write_mode": "recovery_primary",
            "observed_durable_write_ownership_active": True,
            "current_authority_kind": "local_evidence",
            "target_authority_kind": "recovery_storage",
            "local_authoritative": True,
            "authoritative_storage_changed": False,
        }
    )


def _matches_authorization(a, q, receipt, snapshot) -> bool:
    lease = snapshot.lease
    af = snapshot.phase_af_snapshot
    return all(
        (
            a.phase_ai_health_qualification_id == q.id,
            a.phase_ai_health_receipt_id == receipt.id,
            a.durable_write_ownership_lease_id == lease.id,
            a.phase_ag_authorization_id == snapshot.authorization.id,
            a.replica_id == af.replica.id,
            a.phase_ai_health_qualification_hash == q.health_qualification_hash,
            a.phase_ai_health_receipt_hash == receipt.receipt_hash,
            a.phase_ai_request_snapshot_hash == q.request_snapshot_hash,
            a.phase_ai_integrity_proof_hash == q.integrity_proof_hash,
            a.durable_write_ownership_lease_hash == lease.lease_hash,
            a.phase_ag_authorization_hash == snapshot.authorization.authorization_hash,
            a.replica_hash == af.replica.replica_hash,
            a.source_file_hash == q.source_file_hash,
            a.source_file_size_bytes == q.source_file_size_bytes,
            a.local_storage_key_fingerprint == q.local_storage_key_fingerprint,
            a.recovery_bucket_fingerprint == q.recovery_bucket_fingerprint,
            a.candidate_storage_key_fingerprint == q.candidate_storage_key_fingerprint,
            a.source_authority_fingerprint == q.source_authority_fingerprint,
            a.candidate_authority_fingerprint == q.candidate_authority_fingerprint,
            a.configuration_fingerprint == q.configuration_fingerprint,
            a.observed_local_hash == q.observed_local_hash,
            a.observed_local_size_bytes == q.observed_local_size_bytes,
            a.observed_recovery_hash == q.observed_recovery_hash,
            a.observed_recovery_size_bytes == q.observed_recovery_size_bytes,
            a.observed_recovery_etag == q.observed_recovery_etag,
            a.read_route_version_at_request == q.read_route_version_at_request,
            a.experimental_write_route_version_at_request == q.experimental_write_route_version_at_request,
            a.durable_route_version_at_request == q.durable_route_version_at_request,
            a.current_authority_kind == "local_evidence",
            a.target_authority_kind == "recovery_storage",
            a.request_snapshot_hash == _snapshot_hash(q, receipt, snapshot),
            a.phase_ai_requested_by_id == q.requested_by_id,
            a.phase_ai_qualified_by_id == q.qualified_by_id,
            a.phase_ah_activated_by_id == q.phase_ah_activated_by_id,
            a.phase_ag_requested_by_id == q.phase_ag_requested_by_id,
            a.phase_ag_approved_by_id == q.phase_ag_approved_by_id,
            a.phase_af_requested_by_id == q.phase_af_requested_by_id,
            a.phase_af_qualified_by_id == q.phase_af_qualified_by_id,
            a.phase_ae_activated_by_id == q.phase_ae_activated_by_id,
            a.phase_ad_requested_by_id == q.phase_ad_requested_by_id,
            a.phase_ad_approved_by_id == q.phase_ad_approved_by_id,
        )
    )


def _receipt_hash(a, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(a.id),
            "phase_ai_health_qualification_id": str(a.phase_ai_health_qualification_id),
            "phase": phase,
            "health_state": "healthy",
            "current_authority_kind": "local_evidence",
            "target_authority_kind": "recovery_storage",
            "phase_ai_health_qualification_hash": a.phase_ai_health_qualification_hash,
            "phase_ai_health_receipt_hash": a.phase_ai_health_receipt_hash,
            "request_snapshot_hash": a.request_snapshot_hash,
            "authorization_hash": a.authorization_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_authoritative": True,
            "storage_write_performed": False,
            "route_mutation_performed": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "physical_disposal_authorized": False,
            "s3_put_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_overwrite_performed": False,
            "local_move_performed": False,
            "local_delete_performed": False,
        }
    )


def _add_receipt(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt(
        organization_id=a.organization_id,
        claim_id=a.claim_id,
        document_id=a.document_id,
        authorization_id=a.id,
        phase_ai_health_qualification_id=a.phase_ai_health_qualification_id,
        phase=phase,
        health_state="healthy",
        current_authority_kind="local_evidence",
        target_authority_kind="recovery_storage",
        phase_ai_health_qualification_hash=a.phase_ai_health_qualification_hash,
        phase_ai_health_receipt_hash=a.phase_ai_health_receipt_hash,
        request_snapshot_hash=a.request_snapshot_hash,
        authorization_hash=a.authorization_hash,
        receipt_hash=_receipt_hash(a, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
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


def _terminalize(db: Session, a, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    a.status = phase
    a.terminal_by_id = actor_id
    a.terminal_at = now
    a.terminal_reason = reason
    a.authorization_expires_at = None
    db.flush()
    return _add_receipt(db, a, phase=phase, actor_id=actor_id, reason=reason, now=now)


def _forbidden_approvers(a) -> set[UUID]:
    return {
        a.requested_by_id,
        a.phase_ai_requested_by_id,
        a.phase_ai_qualified_by_id,
        a.phase_ah_activated_by_id,
        a.phase_ag_requested_by_id,
        a.phase_ag_approved_by_id,
        a.phase_af_requested_by_id,
        a.phase_af_qualified_by_id,
        a.phase_ae_activated_by_id,
        a.phase_ad_requested_by_id,
        a.phase_ad_approved_by_id,
    }


def request_authoritative_storage_ownership_authorization(
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
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict("Phase AJ request reason is required")
    current = _as_utc(now or _utc_now())
    q, ai_receipt, snapshot = _fresh_ai(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization)
        .where(
            EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.organization_id == organization_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.claim_id == claim_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.document_id == document_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.phase_ai_health_qualification_id == q.id,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
            and _matches_authorization(existing, q, ai_receipt, snapshot)
        ):
            return existing, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Phase AJ authorization already exists for this Phase AI qualification"
        )

    request_snapshot_hash = _snapshot_hash(q, ai_receipt, snapshot)
    review_expires_at = current + AUTHORITATIVE_STORAGE_AUTH_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "request_snapshot_hash": request_snapshot_hash,
            "phase_ai_health_qualification_hash": q.health_qualification_hash,
            "phase_ai_health_receipt_hash": ai_receipt.receipt_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "current_authority_kind": "local_evidence",
            "target_authority_kind": "recovery_storage",
            "max_execution_windows": 1,
            "mode": "phase_aj_authoritative_storage_ownership_authorization",
        }
    )
    af = snapshot.phase_af_snapshot
    a = EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_ai_health_qualification_id=q.id,
        phase_ai_health_receipt_id=ai_receipt.id,
        durable_write_ownership_lease_id=q.durable_write_ownership_lease_id,
        phase_ag_authorization_id=q.authorization_id,
        replica_id=q.replica_id,
        phase_ai_health_qualification_hash=q.health_qualification_hash,
        phase_ai_health_receipt_hash=ai_receipt.receipt_hash,
        phase_ai_request_snapshot_hash=q.request_snapshot_hash,
        phase_ai_integrity_proof_hash=q.integrity_proof_hash,
        durable_write_ownership_lease_hash=snapshot.lease.lease_hash,
        phase_ag_authorization_hash=snapshot.authorization.authorization_hash,
        replica_hash=af.replica.replica_hash,
        source_file_hash=q.source_file_hash,
        source_file_size_bytes=q.source_file_size_bytes,
        local_storage_key_fingerprint=q.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=q.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=q.candidate_storage_key_fingerprint,
        source_authority_fingerprint=q.source_authority_fingerprint,
        candidate_authority_fingerprint=q.candidate_authority_fingerprint,
        configuration_fingerprint=q.configuration_fingerprint,
        observed_local_hash=q.observed_local_hash,
        observed_local_size_bytes=q.observed_local_size_bytes,
        observed_recovery_hash=q.observed_recovery_hash,
        observed_recovery_size_bytes=q.observed_recovery_size_bytes,
        observed_recovery_etag=q.observed_recovery_etag,
        read_route_version_at_request=q.read_route_version_at_request,
        experimental_write_route_version_at_request=q.experimental_write_route_version_at_request,
        durable_route_version_at_request=q.durable_route_version_at_request,
        current_authority_kind="local_evidence",
        target_authority_kind="recovery_storage",
        request_snapshot_hash=request_snapshot_hash,
        authorization_hash=authorization_hash,
        health_state="healthy",
        max_execution_windows=1,
        phase_ai_requested_by_id=q.requested_by_id,
        phase_ai_qualified_by_id=q.qualified_by_id,
        phase_ah_activated_by_id=q.phase_ah_activated_by_id,
        phase_ag_requested_by_id=q.phase_ag_requested_by_id,
        phase_ag_approved_by_id=q.phase_ag_approved_by_id,
        phase_af_requested_by_id=q.phase_af_requested_by_id,
        phase_af_qualified_by_id=q.phase_af_qualified_by_id,
        phase_ae_activated_by_id=q.phase_ae_activated_by_id,
        phase_ad_requested_by_id=q.phase_ad_requested_by_id,
        phase_ad_approved_by_id=q.phase_ad_approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        status="pending_second_approval",
        local_authoritative=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(a)
    db.flush()
    receipt = _add_receipt(db, a, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return a, receipt, "pending_second_approval"


def get_authoritative_storage_ownership_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization).where(
        EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.id == authorization_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.organization_id == organization_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.claim_id == claim_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    a = db.scalar(stmt)
    if a is None:
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound(
            "Phase AJ authoritative-storage ownership authorization not found"
        )
    return a


def approve_authoritative_storage_ownership_authorization(
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
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict("Phase AJ approval reason is required")
    current = _as_utc(now or _utc_now())
    a = get_authoritative_storage_ownership_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if a.status == "approved":
        if a.approved_by_id == approved_by_id and a.approval_reason == normalized_reason:
            return a, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict("Phase AJ authorization is already approved")
    if a.status != "pending_second_approval":
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Only a pending Phase AJ authorization can be approved"
        )
    if current >= _as_utc(a.review_expires_at):
        receipt = _terminalize(
            db,
            a,
            phase="expired",
            actor_id=approved_by_id,
            reason="Phase AJ independent approval window expired",
            now=current,
        )
        return a, receipt, "expired"
    if approved_by_id in _forbidden_approvers(a):
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Phase AJ approver must be independent from requester, AI/AH/AG/AF/AE and AD governance actors"
        )
    try:
        q, ai_receipt, snapshot = _fresh_ai(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=a.phase_ai_health_qualification_id,
        )
    except RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable:
        raise
    except (
        RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound,
        RecoveryAuthoritativeStorageOwnershipAuthorizationConflict,
    ) as exc:
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason=f"Phase AJ fresh verification invalidated: {exc}",
            now=current,
        )
        return a, receipt, "invalidated"
    if not _matches_authorization(a, q, ai_receipt, snapshot):
        receipt = _terminalize(
            db,
            a,
            phase="invalidated",
            actor_id=approved_by_id,
            reason="Phase AJ authorization snapshot drifted before independent approval",
            now=current,
        )
        return a, receipt, "invalidated"

    a.status = "approved"
    a.approved_by_id = approved_by_id
    a.approved_at = current
    a.authorization_expires_at = current + AUTHORITATIVE_STORAGE_AUTH_LIFETIME
    a.approval_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, a, phase="approved", actor_id=approved_by_id, reason=normalized_reason, now=current)
    return a, receipt, "approved"


def reject_authoritative_storage_ownership_authorization(
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
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict("Phase AJ rejection reason is required")
    current = _as_utc(now or _utc_now())
    a = get_authoritative_storage_ownership_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if a.status == "rejected":
        if a.rejected_by_id == rejected_by_id and a.rejection_reason == normalized_reason:
            return a, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict("Phase AJ authorization is already rejected")
    if a.status != "pending_second_approval":
        raise RecoveryAuthoritativeStorageOwnershipAuthorizationConflict(
            "Only a pending Phase AJ authorization can be rejected"
        )
    if current >= _as_utc(a.review_expires_at):
        receipt = _terminalize(
            db,
            a,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase AJ independent approval window expired",
            now=current,
        )
        return a, receipt, "expired"
    a.status = "rejected"
    a.rejected_by_id = rejected_by_id
    a.rejected_at = current
    a.rejection_reason = normalized_reason
    a.terminal_by_id = rejected_by_id
    a.terminal_at = current
    a.terminal_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, a, phase="rejected", actor_id=rejected_by_id, reason=normalized_reason, now=current)
    return a, receipt, "rejected"


def list_authoritative_storage_ownership_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
):
    get_authoritative_storage_ownership_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt)
            .where(
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.authorization_id == authorization_id,
            )
            .order_by(
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.id.asc(),
            )
        ).all()
    )
