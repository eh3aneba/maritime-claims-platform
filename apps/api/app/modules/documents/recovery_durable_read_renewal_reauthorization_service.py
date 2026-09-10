from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_read_renewal_health_models import (
    EvidenceRecoveryDurableReadRenewalHealthQualification,
    EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_health_service import (
    RecoveryDurableReadRenewalHealthConflict,
    RecoveryDurableReadRenewalHealthNotFound,
    RecoveryDurableReadRenewalHealthUnavailable,
    _get_qualification as _get_q_qualification,
    _load_snapshot as _load_q_snapshot,
    _matches_snapshot as _matches_q_snapshot,
)
from app.modules.documents.recovery_durable_read_renewal_reauthorization_models import (
    EvidenceRecoveryDurableReadRenewalReauthorization,
    EvidenceRecoveryDurableReadRenewalReauthorizationReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

REAUTH_REVIEW_WINDOW = timedelta(minutes=10)
REAUTHORIZATION_WINDOW = timedelta(minutes=10)


class RecoveryDurableReadRenewalReauthorizationError(RuntimeError):
    pass


class RecoveryDurableReadRenewalReauthorizationNotFound(RecoveryDurableReadRenewalReauthorizationError):
    pass


class RecoveryDurableReadRenewalReauthorizationConflict(RecoveryDurableReadRenewalReauthorizationError):
    pass


class RecoveryDurableReadRenewalReauthorizationUnavailable(RecoveryDurableReadRenewalReauthorizationError):
    pass


@dataclass(frozen=True)
class DurableReadRenewalReauthorizationSnapshot:
    phase_q_health_qualification_id: UUID
    phase_q_health_receipt_id: UUID
    renewal_lease_id: UUID
    activation_receipt_id: UUID
    terminal_receipt_id: UUID
    prior_renewal_authorization_id: UUID
    phase_n_health_qualification_id: UUID
    prior_durable_lease_id: UUID
    replica_id: UUID
    phase_q_health_qualification_hash: str
    phase_q_request_snapshot_hash: str
    phase_q_health_receipt_hash: str
    operational_evidence_hash: str
    health_state: str
    renewal_lease_hash: str
    lease_snapshot_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    prior_renewal_authorization_hash: str
    phase_n_health_qualification_hash: str
    prior_durable_lease_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    verified_durable_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    route_version_at_request: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    phase_q_qualified_by_id: UUID
    renewal_activated_by_id: UUID
    prior_renewal_authorization_approved_by_id: UUID
    prior_durable_activated_by_id: UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_q_receipt(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableReadRenewalHealthQualification,
) -> EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt).where(
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.organization_id == qualification.organization_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.claim_id == qualification.claim_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.document_id == qualification.document_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.health_qualification_id == qualification.id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadRenewalReauthorizationConflict(
            "Qualified Phase Q health evidence must have exactly one qualified receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.renewal_lease_id == qualification.renewal_lease_id,
            receipt.health_state == qualification.health_state == "healthy",
            receipt.operational_evidence_hash == qualification.operational_evidence_hash,
            receipt.request_snapshot_hash == qualification.request_snapshot_hash,
            receipt.health_qualification_hash == qualification.health_qualification_hash,
            receipt.actor_id == qualification.qualified_by_id,
            qualification.qualified_at is not None,
            _as_utc(receipt.transitioned_at) == _as_utc(qualification.qualified_at),
            receipt.routable_authority_created is False,
            receipt.durable_read_route_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableReadRenewalReauthorizationConflict(
            "Phase Q qualification receipt lineage is inconsistent"
        )
    return receipt


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    phase_q_health_qualification_id: UUID,
) -> DurableReadRenewalReauthorizationSnapshot:
    try:
        qualification = _get_q_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=phase_q_health_qualification_id,
        )
        if not all(
            (
                qualification.status == "qualified",
                qualification.health_state == "healthy",
                qualification.qualified_by_id is not None,
                qualification.qualified_at is not None,
                qualification.verified_durable_read_count >= 1,
                qualification.integrity_failure_count == 0,
                qualification.storage_unavailable_count == 0,
            )
        ):
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Only qualified healthy Phase Q evidence can request another renewal authorization"
            )
        if any(
            (
                qualification.routable_authority_created,
                qualification.durable_read_route_created,
                qualification.read_path_switched,
                qualification.write_path_switched,
                qualification.document_storage_key_mutated,
                qualification.authoritative_storage_changed,
                qualification.destructive_action_performed,
                qualification.s3_delete_performed,
                qualification.local_delete_performed,
            )
        ):
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Phase Q qualification crossed its non-routable safety boundary"
            )

        q_snapshot = _load_q_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            renewal_lease_id=qualification.renewal_lease_id,
        )
        if not _matches_q_snapshot(qualification, q_snapshot):
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Phase Q evidence drifted before renewal reauthorization"
            )
        receipt = _qualified_q_receipt(db, qualification=qualification)
        route = q_snapshot.route
        if not all(
            (
                route.route_class == "local_source",
                route.route_authority_kind == "local",
                route.active_lease_id is None,
                route.active_durable_lease_id is None,
                route.active_durable_renewal_lease_id is None,
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
            )
        ):
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Shared read route changed after Phase Q qualification"
            )
        prior_authorization = q_snapshot.authorization
        if prior_authorization.approved_by_id is None:
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Phase O authorization approval lineage is incomplete"
            )
        prior_lease = q_snapshot.prior_lease
        if prior_lease.activated_by_id is None or q_snapshot.lease.activated_by_id is None:
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Prior durable route activation lineage is incomplete"
            )

        integrity_proof_hash = _canonical_hash(
            {
                "phase_q_health_qualification_id": str(qualification.id),
                "phase_q_health_qualification_hash": qualification.health_qualification_hash,
                "phase_q_health_receipt_id": str(receipt.id),
                "phase_q_health_receipt_hash": receipt.receipt_hash,
                "phase_q_request_snapshot_hash": qualification.request_snapshot_hash,
                "renewal_lease_id": str(qualification.renewal_lease_id),
                "renewal_lease_hash": qualification.renewal_lease_hash,
                "activation_receipt_id": str(qualification.activation_receipt_id),
                "activation_receipt_hash": qualification.activation_receipt_hash,
                "terminal_receipt_id": str(qualification.terminal_receipt_id),
                "terminal_receipt_hash": qualification.terminal_receipt_hash,
                "prior_renewal_authorization_id": str(qualification.authorization_id),
                "prior_renewal_authorization_hash": qualification.authorization_hash,
                "phase_n_health_qualification_id": str(qualification.phase_n_health_qualification_id),
                "phase_n_health_qualification_hash": qualification.phase_n_health_qualification_hash,
                "prior_durable_lease_id": str(qualification.prior_durable_lease_id),
                "prior_durable_lease_hash": qualification.prior_durable_lease_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "verified_durable_read_count": qualification.verified_durable_read_count,
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
                "routable_authority_created": False,
                "read_path_switched": False,
                "write_path_switched": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        request_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "phase_q_health_qualification_id": str(qualification.id),
                "phase_q_health_qualification_hash": qualification.health_qualification_hash,
                "phase_q_health_receipt_hash": receipt.receipt_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "integrity_proof_hash": integrity_proof_hash,
                "route_version_at_request": route.route_version,
                "mode": "phase_r_non_routable_bounded_renewal_reauthorization",
                "routable_authority_created": False,
                "durable_read_route_created": False,
                "read_path_switched": False,
                "write_path_switched": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return DurableReadRenewalReauthorizationSnapshot(
            phase_q_health_qualification_id=qualification.id,
            phase_q_health_receipt_id=receipt.id,
            renewal_lease_id=qualification.renewal_lease_id,
            activation_receipt_id=qualification.activation_receipt_id,
            terminal_receipt_id=qualification.terminal_receipt_id,
            prior_renewal_authorization_id=qualification.authorization_id,
            phase_n_health_qualification_id=qualification.phase_n_health_qualification_id,
            prior_durable_lease_id=qualification.prior_durable_lease_id,
            replica_id=qualification.replica_id,
            phase_q_health_qualification_hash=qualification.health_qualification_hash,
            phase_q_request_snapshot_hash=qualification.request_snapshot_hash,
            phase_q_health_receipt_hash=receipt.receipt_hash,
            operational_evidence_hash=qualification.operational_evidence_hash,
            health_state=qualification.health_state,
            renewal_lease_hash=qualification.renewal_lease_hash,
            lease_snapshot_hash=qualification.lease_snapshot_hash,
            activation_receipt_hash=qualification.activation_receipt_hash,
            terminal_receipt_hash=qualification.terminal_receipt_hash,
            prior_renewal_authorization_hash=qualification.authorization_hash,
            phase_n_health_qualification_hash=qualification.phase_n_health_qualification_hash,
            prior_durable_lease_hash=qualification.prior_durable_lease_hash,
            replica_hash=qualification.replica_hash,
            source_file_hash=qualification.source_file_hash,
            source_file_size_bytes=qualification.source_file_size_bytes,
            local_storage_key_fingerprint=qualification.local_storage_key_fingerprint,
            recovery_bucket_fingerprint=qualification.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=qualification.candidate_storage_key_fingerprint,
            source_authority_fingerprint=qualification.source_authority_fingerprint,
            candidate_authority_fingerprint=qualification.candidate_authority_fingerprint,
            configuration_fingerprint=qualification.configuration_fingerprint,
            verified_durable_read_count=qualification.verified_durable_read_count,
            integrity_failure_count=qualification.integrity_failure_count,
            storage_unavailable_count=qualification.storage_unavailable_count,
            route_expired_attempt_count=qualification.route_expired_attempt_count,
            operational_event_count=qualification.operational_event_count,
            route_version_at_request=route.route_version,
            integrity_proof_hash=integrity_proof_hash,
            request_snapshot_hash=request_snapshot_hash,
            phase_q_qualified_by_id=qualification.qualified_by_id,
            renewal_activated_by_id=q_snapshot.lease.activated_by_id,
            prior_renewal_authorization_approved_by_id=prior_authorization.approved_by_id,
            prior_durable_activated_by_id=prior_lease.activated_by_id,
        )
    except RecoveryDurableReadRenewalReauthorizationError:
        raise
    except RecoveryDurableReadRenewalHealthNotFound as exc:
        raise RecoveryDurableReadRenewalReauthorizationNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalHealthConflict as exc:
        raise RecoveryDurableReadRenewalReauthorizationConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalHealthUnavailable as exc:
        raise RecoveryDurableReadRenewalReauthorizationUnavailable(str(exc)) from exc


def _matches_snapshot(
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
    snapshot: DurableReadRenewalReauthorizationSnapshot,
) -> bool:
    return all(
        getattr(authorization, field) == getattr(snapshot, field)
        for field in DurableReadRenewalReauthorizationSnapshot.__dataclass_fields__
    )


def _new_receipt(
    *,
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadRenewalReauthorizationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "reauthorization_id": str(authorization.id),
            "phase_q_health_qualification_id": str(authorization.phase_q_health_qualification_id),
            "renewal_lease_id": str(authorization.renewal_lease_id),
            "phase": phase,
            "health_state": authorization.health_state,
            "operational_evidence_hash": authorization.operational_evidence_hash,
            "integrity_proof_hash": authorization.integrity_proof_hash,
            "request_snapshot_hash": authorization.request_snapshot_hash,
            "authorization_hash": authorization.authorization_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": False,
            "durable_read_route_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryDurableReadRenewalReauthorizationReceipt(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        reauthorization_id=authorization.id,
        phase_q_health_qualification_id=authorization.phase_q_health_qualification_id,
        renewal_lease_id=authorization.renewal_lease_id,
        phase=phase,
        health_state=authorization.health_state,
        operational_evidence_hash=authorization.operational_evidence_hash,
        integrity_proof_hash=authorization.integrity_proof_hash,
        request_snapshot_hash=authorization.request_snapshot_hash,
        authorization_hash=authorization.authorization_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=False,
        durable_read_route_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )


def _terminalize(
    db: Session,
    *,
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadRenewalReauthorizationReceipt:
    authorization.status = status
    authorization.authorization_expires_at = None
    authorization.terminal_by_id = actor_id
    authorization.terminal_at = now
    authorization.terminal_reason = reason
    receipt = _new_receipt(
        authorization=authorization,
        phase=status,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDurableReadRenewalReauthorization:
    stmt = select(EvidenceRecoveryDurableReadRenewalReauthorization).where(
        EvidenceRecoveryDurableReadRenewalReauthorization.id == authorization_id,
        EvidenceRecoveryDurableReadRenewalReauthorization.organization_id == organization_id,
        EvidenceRecoveryDurableReadRenewalReauthorization.claim_id == claim_id,
        EvidenceRecoveryDurableReadRenewalReauthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RecoveryDurableReadRenewalReauthorizationNotFound(
            "Recovery durable read renewal reauthorization not found"
        )
    return authorization


def request_durable_read_renewal_reauthorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    phase_q_health_qualification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalReauthorization, EvidenceRecoveryDurableReadRenewalReauthorizationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalReauthorizationConflict("Renewal reauthorization request reason is required")
    current_time = _as_utc(now or _utc_now())
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalReauthorization)
        .where(
            EvidenceRecoveryDurableReadRenewalReauthorization.organization_id == organization_id,
            EvidenceRecoveryDurableReadRenewalReauthorization.phase_q_health_qualification_id == phase_q_health_qualification_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id != requested_by_id or existing.request_reason != normalized_reason:
            raise RecoveryDurableReadRenewalReauthorizationConflict(
                "Phase R request replay must use the original requester and reason"
            )
        if existing.status == "pending_second_approval" and current_time >= _as_utc(existing.review_expires_at):
            receipt = _terminalize(
                db,
                authorization=existing,
                status="expired",
                actor_id=requested_by_id,
                reason="Phase R second-approval window expired",
                now=current_time,
            )
            return existing, receipt, "expired"
        if existing.status != "pending_second_approval":
            return existing, None, "unchanged"
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_q_health_qualification_id=phase_q_health_qualification_id,
        )
        if not _matches_snapshot(existing, snapshot):
            receipt = _terminalize(
                db,
                authorization=existing,
                status="invalidated",
                actor_id=requested_by_id,
                reason="Phase Q evidence drifted before Phase R request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_q_health_qualification_id=phase_q_health_qualification_id,
    )
    review_expires_at = current_time + REAUTH_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "phase_q_health_qualification_id": str(phase_q_health_qualification_id),
            "phase_q_health_qualification_hash": snapshot.phase_q_health_qualification_hash,
            "phase_q_health_receipt_hash": snapshot.phase_q_health_receipt_hash,
            "operational_evidence_hash": snapshot.operational_evidence_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "mode": "phase_r_non_routable_bounded_renewal_reauthorization",
        }
    )
    authorization = EvidenceRecoveryDurableReadRenewalReauthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        **snapshot.__dict__,
        authorization_hash=authorization_hash,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        requested_at=current_time,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        authorization_expires_at=None,
        routable_authority_created=False,
        durable_read_route_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(authorization)
    db.flush()
    receipt = _new_receipt(
        authorization=authorization,
        phase="requested",
        actor_id=requested_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "pending_second_approval"


def approve_durable_read_renewal_reauthorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalReauthorization, EvidenceRecoveryDurableReadRenewalReauthorizationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalReauthorizationConflict("Renewal reauthorization approval reason is required")
    current_time = _as_utc(now or _utc_now())
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if authorization.status == "approved":
        if authorization.approved_by_id == approved_by_id and authorization.approval_reason == normalized_reason:
            return authorization, None, "unchanged"
        raise RecoveryDurableReadRenewalReauthorizationConflict(
            "Approved Phase R replay does not match the original approval"
        )
    if authorization.status != "pending_second_approval":
        raise RecoveryDurableReadRenewalReauthorizationConflict("Only a pending Phase R authorization can be approved")
    if current_time >= _as_utc(authorization.review_expires_at):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="expired",
            actor_id=approved_by_id,
            reason="Phase R second-approval window expired",
            now=current_time,
        )
        return authorization, receipt, "expired"
    if approved_by_id in {
        authorization.requested_by_id,
        authorization.phase_q_qualified_by_id,
        authorization.renewal_activated_by_id,
        authorization.prior_renewal_authorization_approved_by_id,
        authorization.prior_durable_activated_by_id,
    }:
        raise RecoveryDurableReadRenewalReauthorizationConflict(
            "Phase R approver must be independent from the requester and prior qualification/routing/authorization actors"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_q_health_qualification_id=authorization.phase_q_health_qualification_id,
        )
    except RecoveryDurableReadRenewalReauthorizationUnavailable:
        raise
    except (RecoveryDurableReadRenewalReauthorizationNotFound, RecoveryDurableReadRenewalReauthorizationConflict) as exc:
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh Phase R preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return authorization, receipt, "invalidated"
    if not _matches_snapshot(authorization, snapshot):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Phase R authorization snapshot drifted before approval",
            now=current_time,
        )
        return authorization, receipt, "invalidated"

    authorization.status = "approved"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current_time
    authorization.authorization_expires_at = current_time + REAUTHORIZATION_WINDOW
    authorization.approval_reason = normalized_reason
    receipt = _new_receipt(
        authorization=authorization,
        phase="approved",
        actor_id=approved_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "approved"


def reject_durable_read_renewal_reauthorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalReauthorization, EvidenceRecoveryDurableReadRenewalReauthorizationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalReauthorizationConflict("Renewal reauthorization rejection reason is required")
    current_time = _as_utc(now or _utc_now())
    authorization = _get_authorization(
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
        raise RecoveryDurableReadRenewalReauthorizationConflict(
            "Rejected Phase R replay does not match the original rejection"
        )
    if authorization.status != "pending_second_approval":
        raise RecoveryDurableReadRenewalReauthorizationConflict("Only a pending Phase R authorization can be rejected")
    authorization.status = "rejected"
    authorization.rejected_by_id = rejected_by_id
    authorization.rejected_at = current_time
    authorization.rejection_reason = normalized_reason
    receipt = _new_receipt(
        authorization=authorization,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "rejected"


def get_durable_read_renewal_reauthorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> EvidenceRecoveryDurableReadRenewalReauthorization:
    return _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )


def list_durable_read_renewal_reauthorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> list[EvidenceRecoveryDurableReadRenewalReauthorizationReceipt]:
    _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalReauthorizationReceipt)
            .where(
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.reauthorization_id == authorization_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.id.asc(),
            )
        ).all()
    )
