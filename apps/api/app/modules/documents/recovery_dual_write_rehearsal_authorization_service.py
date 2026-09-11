from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_dual_write_rehearsal_authorization_models import (
    EvidenceRecoveryDualWriteRehearsalAuthorization,
    EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_ownership_transition_health_models import (
    EvidenceRecoveryReadOwnershipTransitionHealthQualification,
    EvidenceRecoveryReadOwnershipTransitionHealthReceipt,
)
from app.modules.documents.recovery_read_ownership_transition_health_service import (
    RecoveryReadOwnershipTransitionHealthConflict,
    RecoveryReadOwnershipTransitionHealthNotFound,
    RecoveryReadOwnershipTransitionHealthUnavailable,
    _load_snapshot as _load_w_snapshot,
    _matches_snapshot as _matches_w_snapshot,
    get_recovery_read_ownership_transition_health_qualification,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

DUAL_WRITE_REHEARSAL_REVIEW_WINDOW = timedelta(minutes=10)
DUAL_WRITE_REHEARSAL_AUTHORIZATION_WINDOW = timedelta(minutes=10)


class RecoveryDualWriteRehearsalAuthorizationError(RuntimeError):
    pass


class RecoveryDualWriteRehearsalAuthorizationNotFound(RecoveryDualWriteRehearsalAuthorizationError):
    pass


class RecoveryDualWriteRehearsalAuthorizationConflict(RecoveryDualWriteRehearsalAuthorizationError):
    pass


class RecoveryDualWriteRehearsalAuthorizationUnavailable(RecoveryDualWriteRehearsalAuthorizationError):
    pass


@dataclass(frozen=True)
class DualWriteRehearsalAuthorizationSnapshot:
    phase_w_health_qualification_id: UUID
    phase_w_health_receipt_id: UUID
    phase_v_transition_lease_id: UUID
    phase_u_authorization_id: UUID
    phase_t_health_qualification_id: UUID
    replica_id: UUID
    phase_w_health_qualification_hash: str
    phase_w_request_snapshot_hash: str
    phase_w_health_receipt_hash: str
    operational_evidence_hash: str
    health_state: str
    phase_v_transition_lease_hash: str
    phase_u_authorization_hash: str
    phase_t_health_qualification_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    verified_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    route_version_at_request: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    phase_w_qualified_by_id: UUID
    phase_v_activated_by_id: UUID
    phase_u_approved_by_id: UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_w_receipt(
    db: Session,
    *,
    qualification: EvidenceRecoveryReadOwnershipTransitionHealthQualification,
) -> EvidenceRecoveryReadOwnershipTransitionHealthReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryReadOwnershipTransitionHealthReceipt).where(
                EvidenceRecoveryReadOwnershipTransitionHealthReceipt.organization_id == qualification.organization_id,
                EvidenceRecoveryReadOwnershipTransitionHealthReceipt.claim_id == qualification.claim_id,
                EvidenceRecoveryReadOwnershipTransitionHealthReceipt.document_id == qualification.document_id,
                EvidenceRecoveryReadOwnershipTransitionHealthReceipt.health_qualification_id == qualification.id,
                EvidenceRecoveryReadOwnershipTransitionHealthReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDualWriteRehearsalAuthorizationConflict(
            "Qualified Phase W evidence must have exactly one qualified receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.transition_lease_id == qualification.transition_lease_id,
            receipt.health_state == qualification.health_state == "healthy",
            receipt.operational_evidence_hash == qualification.operational_evidence_hash,
            receipt.request_snapshot_hash == qualification.request_snapshot_hash,
            receipt.health_qualification_hash == qualification.health_qualification_hash,
            receipt.actor_id == qualification.qualified_by_id,
            qualification.qualified_at is not None,
            _as_utc(receipt.transitioned_at) == _as_utc(qualification.qualified_at),
            receipt.routable_authority_created is False,
            receipt.durable_read_route_created is False,
            receipt.read_ownership_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDualWriteRehearsalAuthorizationConflict(
            "Phase W qualified receipt lineage is inconsistent"
        )
    return receipt


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    phase_w_health_qualification_id: UUID,
) -> DualWriteRehearsalAuthorizationSnapshot:
    try:
        qualification = get_recovery_read_ownership_transition_health_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=phase_w_health_qualification_id,
        )
        if not all(
            (
                qualification.status == "qualified",
                qualification.health_state == "healthy",
                qualification.qualified_by_id is not None,
                qualification.qualified_at is not None,
                qualification.verified_read_count >= 1,
                qualification.integrity_failure_count == 0,
                qualification.storage_unavailable_count == 0,
            )
        ):
            raise RecoveryDualWriteRehearsalAuthorizationConflict(
                "Only qualified healthy Phase W evidence may authorize a dual-write rehearsal"
            )
        if any(
            (
                qualification.routable_authority_created,
                qualification.durable_read_route_created,
                qualification.read_ownership_authority_created,
                qualification.read_path_switched,
                qualification.write_path_switched,
                qualification.document_storage_key_mutated,
                qualification.authoritative_storage_changed,
                qualification.destructive_action_performed,
                qualification.s3_delete_performed,
                qualification.local_delete_performed,
            )
        ):
            raise RecoveryDualWriteRehearsalAuthorizationConflict(
                "Phase W qualification crossed its evidence-only safety boundary"
            )

        w_snapshot = _load_w_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            transition_lease_id=qualification.transition_lease_id,
        )
        if not _matches_w_snapshot(qualification, w_snapshot):
            raise RecoveryDualWriteRehearsalAuthorizationConflict(
                "Phase W evidence drifted before dual-write rehearsal authorization"
            )
        receipt = _qualified_w_receipt(db, qualification=qualification)
        lease = w_snapshot.lease
        route = w_snapshot.route
        if not all(
            (
                route.route_class == "local_source",
                route.route_authority_kind == "local",
                route.active_lease_id is None,
                route.active_durable_lease_id is None,
                route.active_durable_renewal_lease_id is None,
                route.active_durable_reauthorized_renewal_lease_id is None,
                route.active_read_ownership_transition_lease_id is None,
                route.active_replica_id is None,
                route.read_path_switched is False,
                route.write_path_switched is False,
                route.document_storage_key_mutated is False,
                route.authoritative_storage_changed is False,
                route.destructive_action_performed is False,
                route.route_version == qualification.route_version_at_request,
                route.source_authority_fingerprint == qualification.source_authority_fingerprint,
                route.candidate_authority_fingerprint == qualification.candidate_authority_fingerprint,
                route.configuration_fingerprint == qualification.configuration_fingerprint,
                lease.activated_by_id is not None,
                lease.authorization_approved_by_id is not None,
            )
        ):
            raise RecoveryDualWriteRehearsalAuthorizationConflict(
                "Shared route or Phase V actor lineage changed after Phase W qualification"
            )

        integrity_proof_hash = _canonical_hash(
            {
                "phase_w_health_qualification_id": str(qualification.id),
                "phase_w_health_qualification_hash": qualification.health_qualification_hash,
                "phase_w_health_receipt_id": str(receipt.id),
                "phase_w_health_receipt_hash": receipt.receipt_hash,
                "phase_w_request_snapshot_hash": qualification.request_snapshot_hash,
                "phase_v_transition_lease_id": str(qualification.transition_lease_id),
                "phase_v_transition_lease_hash": qualification.transition_lease_hash,
                "phase_u_authorization_id": str(qualification.authorization_id),
                "phase_u_authorization_hash": qualification.authorization_hash,
                "phase_t_health_qualification_id": str(qualification.phase_t_health_qualification_id),
                "phase_t_health_qualification_hash": qualification.phase_t_health_qualification_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "verified_read_count": qualification.verified_read_count,
                "integrity_failure_count": qualification.integrity_failure_count,
                "storage_unavailable_count": qualification.storage_unavailable_count,
                "route_expired_attempt_count": qualification.route_expired_attempt_count,
                "operational_event_count": qualification.operational_event_count,
                "replica_id": str(qualification.replica_id),
                "replica_hash": qualification.replica_hash,
                "source_file_hash": qualification.source_file_hash,
                "source_file_size_bytes": qualification.source_file_size_bytes,
                "local_storage_key_fingerprint": qualification.local_storage_key_fingerprint,
                "recovery_bucket_fingerprint": qualification.recovery_bucket_fingerprint,
                "candidate_storage_key_fingerprint": qualification.candidate_storage_key_fingerprint,
                "route_version": route.route_version,
                "route_class": route.route_class,
                "route_authority_kind": route.route_authority_kind,
                "source_authority_fingerprint": qualification.source_authority_fingerprint,
                "candidate_authority_fingerprint": qualification.candidate_authority_fingerprint,
                "configuration_fingerprint": qualification.configuration_fingerprint,
                "rehearsal_executed": False,
                "dual_write_active": False,
                "durable_write_authority_created": False,
                "read_path_switched": False,
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
                "s3_copy_performed": False,
                "s3_delete_performed": False,
                "local_delete_performed": False,
            }
        )
        request_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "phase_w_health_qualification_id": str(qualification.id),
                "phase_w_health_qualification_hash": qualification.health_qualification_hash,
                "phase_w_health_receipt_hash": receipt.receipt_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "integrity_proof_hash": integrity_proof_hash,
                "route_version_at_request": route.route_version,
                "max_rehearsal_writes": 1,
                "mode": "phase_x_non_executing_dual_write_rehearsal_authorization",
            }
        )
        return DualWriteRehearsalAuthorizationSnapshot(
            phase_w_health_qualification_id=qualification.id,
            phase_w_health_receipt_id=receipt.id,
            phase_v_transition_lease_id=qualification.transition_lease_id,
            phase_u_authorization_id=qualification.authorization_id,
            phase_t_health_qualification_id=qualification.phase_t_health_qualification_id,
            replica_id=qualification.replica_id,
            phase_w_health_qualification_hash=qualification.health_qualification_hash,
            phase_w_request_snapshot_hash=qualification.request_snapshot_hash,
            phase_w_health_receipt_hash=receipt.receipt_hash,
            operational_evidence_hash=qualification.operational_evidence_hash,
            health_state=qualification.health_state,
            phase_v_transition_lease_hash=qualification.transition_lease_hash,
            phase_u_authorization_hash=qualification.authorization_hash,
            phase_t_health_qualification_hash=qualification.phase_t_health_qualification_hash,
            replica_hash=qualification.replica_hash,
            source_file_hash=qualification.source_file_hash,
            source_file_size_bytes=qualification.source_file_size_bytes,
            local_storage_key_fingerprint=qualification.local_storage_key_fingerprint,
            recovery_bucket_fingerprint=qualification.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=qualification.candidate_storage_key_fingerprint,
            source_authority_fingerprint=qualification.source_authority_fingerprint,
            candidate_authority_fingerprint=qualification.candidate_authority_fingerprint,
            configuration_fingerprint=qualification.configuration_fingerprint,
            verified_read_count=qualification.verified_read_count,
            integrity_failure_count=qualification.integrity_failure_count,
            storage_unavailable_count=qualification.storage_unavailable_count,
            route_expired_attempt_count=qualification.route_expired_attempt_count,
            operational_event_count=qualification.operational_event_count,
            route_version_at_request=route.route_version,
            integrity_proof_hash=integrity_proof_hash,
            request_snapshot_hash=request_snapshot_hash,
            phase_w_qualified_by_id=qualification.qualified_by_id,
            phase_v_activated_by_id=lease.activated_by_id,
            phase_u_approved_by_id=lease.authorization_approved_by_id,
        )
    except RecoveryDualWriteRehearsalAuthorizationError:
        raise
    except RecoveryReadOwnershipTransitionHealthNotFound as exc:
        raise RecoveryDualWriteRehearsalAuthorizationNotFound(str(exc)) from exc
    except RecoveryReadOwnershipTransitionHealthConflict as exc:
        raise RecoveryDualWriteRehearsalAuthorizationConflict(str(exc)) from exc
    except RecoveryReadOwnershipTransitionHealthUnavailable as exc:
        raise RecoveryDualWriteRehearsalAuthorizationUnavailable(str(exc)) from exc


def _matches_snapshot(
    authorization: EvidenceRecoveryDualWriteRehearsalAuthorization,
    snapshot: DualWriteRehearsalAuthorizationSnapshot,
) -> bool:
    return all(
        getattr(authorization, field) == getattr(snapshot, field)
        for field in DualWriteRehearsalAuthorizationSnapshot.__dataclass_fields__
    )


def _new_receipt(
    authorization: EvidenceRecoveryDualWriteRehearsalAuthorization,
    *,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "phase_w_health_qualification_id": str(authorization.phase_w_health_qualification_id),
            "phase": phase,
            "health_state": authorization.health_state,
            "operational_evidence_hash": authorization.operational_evidence_hash,
            "integrity_proof_hash": authorization.integrity_proof_hash,
            "request_snapshot_hash": authorization.request_snapshot_hash,
            "authorization_hash": authorization.authorization_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(now),
            "rehearsal_executed": False,
            "dual_write_active": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        authorization_id=authorization.id,
        phase_w_health_qualification_id=authorization.phase_w_health_qualification_id,
        phase=phase,
        health_state=authorization.health_state,
        operational_evidence_hash=authorization.operational_evidence_hash,
        integrity_proof_hash=authorization.integrity_proof_hash,
        request_snapshot_hash=authorization.request_snapshot_hash,
        authorization_hash=authorization.authorization_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=now,
        rehearsal_executed=False,
        dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )


def _terminalize(db: Session, authorization: EvidenceRecoveryDualWriteRehearsalAuthorization, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    authorization.status = phase
    authorization.terminal_by_id = actor_id
    authorization.terminal_at = now
    authorization.terminal_reason = reason
    receipt = _new_receipt(authorization, phase=phase, actor_id=actor_id, reason=reason, now=now)
    db.add(receipt)
    db.flush()
    return receipt


def get_dual_write_rehearsal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDualWriteRehearsalAuthorization:
    stmt = select(EvidenceRecoveryDualWriteRehearsalAuthorization).where(
        EvidenceRecoveryDualWriteRehearsalAuthorization.id == authorization_id,
        EvidenceRecoveryDualWriteRehearsalAuthorization.organization_id == organization_id,
        EvidenceRecoveryDualWriteRehearsalAuthorization.claim_id == claim_id,
        EvidenceRecoveryDualWriteRehearsalAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RecoveryDualWriteRehearsalAuthorizationNotFound("Phase X dual-write rehearsal authorization not found")
    return authorization


def request_dual_write_rehearsal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    phase_w_health_qualification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDualWriteRehearsalAuthorizationConflict("Phase X request reason is required")
    current = _as_utc(now or _utc_now())
    existing = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalAuthorization)
        .where(
            EvidenceRecoveryDualWriteRehearsalAuthorization.organization_id == organization_id,
            EvidenceRecoveryDualWriteRehearsalAuthorization.phase_w_health_qualification_id == phase_w_health_qualification_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id != requested_by_id or existing.request_reason != normalized_reason:
            raise RecoveryDualWriteRehearsalAuthorizationConflict(
                "Phase X request replay must use the original requester and reason"
            )
        if existing.status == "pending_second_approval" and current >= _as_utc(existing.review_expires_at):
            receipt = _terminalize(
                db,
                existing,
                phase="expired",
                actor_id=requested_by_id,
                reason="Phase X second-approval window expired",
                now=current,
            )
            return existing, receipt, "expired"
        if existing.status != "pending_second_approval":
            return existing, None, "unchanged"
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_w_health_qualification_id=phase_w_health_qualification_id,
        )
        if not _matches_snapshot(existing, snapshot):
            receipt = _terminalize(
                db,
                existing,
                phase="invalidated",
                actor_id=requested_by_id,
                reason="Phase W evidence drifted before Phase X request replay",
                now=current,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_w_health_qualification_id=phase_w_health_qualification_id,
    )
    review_expires_at = current + DUAL_WRITE_REHEARSAL_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "phase_w_health_qualification_id": str(snapshot.phase_w_health_qualification_id),
            "phase_w_health_qualification_hash": snapshot.phase_w_health_qualification_hash,
            "phase_w_health_receipt_hash": snapshot.phase_w_health_receipt_hash,
            "operational_evidence_hash": snapshot.operational_evidence_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "max_rehearsal_writes": 1,
            "mode": "phase_x_dual_write_rehearsal_authorization",
        }
    )
    authorization = EvidenceRecoveryDualWriteRehearsalAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        **{
            field: getattr(snapshot, field)
            for field in DualWriteRehearsalAuthorizationSnapshot.__dataclass_fields__
        },
        authorization_hash=authorization_hash,
        max_rehearsal_writes=1,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        rehearsal_executed=False,
        dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(authorization)
    db.flush()
    receipt = _new_receipt(
        authorization,
        phase="requested",
        actor_id=requested_by_id,
        reason=normalized_reason,
        now=current,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "pending_second_approval"


def approve_dual_write_rehearsal_authorization(
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
        raise RecoveryDualWriteRehearsalAuthorizationConflict("Phase X approval reason is required")
    current = _as_utc(now or _utc_now())
    authorization = get_dual_write_rehearsal_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if authorization.status == "approved":
        return authorization, None, "unchanged"
    if authorization.status != "pending_second_approval":
        raise RecoveryDualWriteRehearsalAuthorizationConflict("Only pending Phase X authorization can be approved")
    if current >= _as_utc(authorization.review_expires_at):
        receipt = _terminalize(
            db,
            authorization,
            phase="expired",
            actor_id=approved_by_id,
            reason="Phase X second-approval window expired",
            now=current,
        )
        return authorization, receipt, "expired"
    if approved_by_id in {
        authorization.requested_by_id,
        authorization.phase_w_qualified_by_id,
        authorization.phase_v_activated_by_id,
        authorization.phase_u_approved_by_id,
    }:
        raise RecoveryDualWriteRehearsalAuthorizationConflict(
            "Phase X approver must be independent from requester, Phase W qualifier, Phase V activator and Phase U approver"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_w_health_qualification_id=authorization.phase_w_health_qualification_id,
        )
    except RecoveryDualWriteRehearsalAuthorizationUnavailable:
        raise
    except (RecoveryDualWriteRehearsalAuthorizationNotFound, RecoveryDualWriteRehearsalAuthorizationConflict) as exc:
        receipt = _terminalize(
            db,
            authorization,
            phase="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh Phase X preflight failed: {type(exc).__name__}",
            now=current,
        )
        return authorization, receipt, "invalidated"
    if not _matches_snapshot(authorization, snapshot):
        receipt = _terminalize(
            db,
            authorization,
            phase="invalidated",
            actor_id=approved_by_id,
            reason="Phase W snapshot drifted before Phase X second approval",
            now=current,
        )
        return authorization, receipt, "invalidated"

    authorization.status = "approved"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current
    authorization.authorization_expires_at = current + DUAL_WRITE_REHEARSAL_AUTHORIZATION_WINDOW
    authorization.approval_reason = normalized_reason
    receipt = _new_receipt(
        authorization,
        phase="approved",
        actor_id=approved_by_id,
        reason=normalized_reason,
        now=current,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "approved"


def reject_dual_write_rehearsal_authorization(
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
        raise RecoveryDualWriteRehearsalAuthorizationConflict("Phase X rejection reason is required")
    current = _as_utc(now or _utc_now())
    authorization = get_dual_write_rehearsal_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if authorization.status == "rejected":
        if authorization.rejected_by_id == rejected_by_id and authorization.rejection_reason == normalized_reason:
            return authorization, None, "unchanged"
        raise RecoveryDualWriteRehearsalAuthorizationConflict("Phase X rejection replay does not match")
    if authorization.status != "pending_second_approval":
        raise RecoveryDualWriteRehearsalAuthorizationConflict("Only pending Phase X authorization can be rejected")
    if current >= _as_utc(authorization.review_expires_at):
        receipt = _terminalize(
            db,
            authorization,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase X second-approval window expired",
            now=current,
        )
        return authorization, receipt, "expired"
    authorization.status = "rejected"
    authorization.rejected_by_id = rejected_by_id
    authorization.rejected_at = current
    authorization.rejection_reason = normalized_reason
    receipt = _new_receipt(
        authorization,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        now=current,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "rejected"


def list_dual_write_rehearsal_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
):
    get_dual_write_rehearsal_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt)
            .where(
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.authorization_id == authorization_id,
            )
            .order_by(EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.transitioned_at.asc())
        ).all()
    )
