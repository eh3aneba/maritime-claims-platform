from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_service import (
    RecoveryDurableReadReauthorizedRenewalHealthConflict,
    RecoveryDurableReadReauthorizedRenewalHealthNotFound,
    RecoveryDurableReadReauthorizedRenewalHealthUnavailable,
    _get_qualification as _get_t_qualification,
    _load_snapshot as _load_t_snapshot,
    _matches_snapshot as _matches_t_snapshot,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_ownership_transition_authorization_models import (
    EvidenceRecoveryReadOwnershipTransitionAuthorization,
    EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

READ_OWNERSHIP_REVIEW_WINDOW = timedelta(minutes=10)
READ_OWNERSHIP_AUTHORIZATION_WINDOW = timedelta(minutes=10)


class RecoveryReadOwnershipTransitionAuthorizationError(RuntimeError):
    pass


class RecoveryReadOwnershipTransitionAuthorizationNotFound(
    RecoveryReadOwnershipTransitionAuthorizationError
):
    pass


class RecoveryReadOwnershipTransitionAuthorizationConflict(
    RecoveryReadOwnershipTransitionAuthorizationError
):
    pass


class RecoveryReadOwnershipTransitionAuthorizationUnavailable(
    RecoveryReadOwnershipTransitionAuthorizationError
):
    pass


@dataclass(frozen=True)
class ReadOwnershipTransitionAuthorizationSnapshot:
    phase_t_health_qualification_id: UUID
    phase_t_health_receipt_id: UUID
    reauthorized_renewal_lease_id: UUID
    activation_receipt_id: UUID
    terminal_receipt_id: UUID
    reauthorization_id: UUID
    phase_q_health_qualification_id: UUID
    prior_renewal_lease_id: UUID
    replica_id: UUID
    phase_t_health_qualification_hash: str
    phase_t_request_snapshot_hash: str
    phase_t_health_receipt_hash: str
    operational_evidence_hash: str
    health_state: str
    reauthorized_renewal_lease_hash: str
    lease_snapshot_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    reauthorization_hash: str
    phase_q_health_qualification_hash: str
    prior_renewal_lease_hash: str
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
    phase_t_qualified_by_id: UUID
    reauthorized_renewal_activated_by_id: UUID
    reauthorization_approved_by_id: UUID
    phase_q_qualified_by_id: UUID
    prior_renewal_activated_by_id: UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualified_t_receipt(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt).where(
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.organization_id
                == qualification.organization_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.claim_id
                == qualification.claim_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.document_id
                == qualification.document_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.health_qualification_id
                == qualification.id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.phase
                == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Qualified Phase T health evidence must have exactly one qualified receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.reauthorized_renewal_lease_id
            == qualification.reauthorized_renewal_lease_id,
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
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Phase T qualified receipt lineage is inconsistent"
        )
    return receipt


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    phase_t_health_qualification_id: UUID,
) -> ReadOwnershipTransitionAuthorizationSnapshot:
    try:
        qualification = _get_t_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=phase_t_health_qualification_id,
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
            raise RecoveryReadOwnershipTransitionAuthorizationConflict(
                "Only healthy qualified Phase T evidence can request read-ownership transition authorization"
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
            raise RecoveryReadOwnershipTransitionAuthorizationConflict(
                "Phase T qualification crossed its non-routable safety boundary"
            )

        t_snapshot = _load_t_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            reauthorized_renewal_lease_id=qualification.reauthorized_renewal_lease_id,
        )
        if not _matches_t_snapshot(qualification, t_snapshot):
            raise RecoveryReadOwnershipTransitionAuthorizationConflict(
                "Phase T evidence drifted before read-ownership transition authorization"
            )
        receipt = _qualified_t_receipt(db, qualification=qualification)
        route = t_snapshot.route
        if not all(
            (
                route.route_class == "local_source",
                route.route_authority_kind == "local",
                route.active_lease_id is None,
                route.active_durable_lease_id is None,
                route.active_durable_renewal_lease_id is None,
                route.active_durable_reauthorized_renewal_lease_id is None,
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
            raise RecoveryReadOwnershipTransitionAuthorizationConflict(
                "Shared read route changed after Phase T qualification"
            )
        lease = t_snapshot.lease
        reauthorization = t_snapshot.reauthorization
        phase_q = t_snapshot.phase_q_health
        prior_lease = t_snapshot.prior_renewal_lease
        if not all(
            (
                lease.activated_by_id is not None,
                reauthorization.approved_by_id is not None,
                phase_q.qualified_by_id is not None,
                prior_lease.activated_by_id is not None,
            )
        ):
            raise RecoveryReadOwnershipTransitionAuthorizationConflict(
                "Phase T actor lineage is incomplete"
            )

        integrity_proof_hash = _canonical_hash(
            {
                "phase_t_health_qualification_id": str(qualification.id),
                "phase_t_health_qualification_hash": qualification.health_qualification_hash,
                "phase_t_health_receipt_id": str(receipt.id),
                "phase_t_health_receipt_hash": receipt.receipt_hash,
                "phase_t_request_snapshot_hash": qualification.request_snapshot_hash,
                "reauthorized_renewal_lease_id": str(qualification.reauthorized_renewal_lease_id),
                "reauthorized_renewal_lease_hash": qualification.reauthorized_renewal_lease_hash,
                "activation_receipt_id": str(qualification.activation_receipt_id),
                "activation_receipt_hash": qualification.activation_receipt_hash,
                "terminal_receipt_id": str(qualification.terminal_receipt_id),
                "terminal_receipt_hash": qualification.terminal_receipt_hash,
                "reauthorization_id": str(qualification.reauthorization_id),
                "reauthorization_hash": qualification.reauthorization_hash,
                "phase_q_health_qualification_id": str(qualification.phase_q_health_qualification_id),
                "phase_q_health_qualification_hash": qualification.phase_q_health_qualification_hash,
                "prior_renewal_lease_id": str(qualification.prior_renewal_lease_id),
                "prior_renewal_lease_hash": qualification.prior_renewal_lease_hash,
                "replica_id": str(qualification.replica_id),
                "replica_hash": qualification.replica_hash,
                "source_file_hash": qualification.source_file_hash,
                "source_file_size_bytes": qualification.source_file_size_bytes,
                "local_storage_key_fingerprint": qualification.local_storage_key_fingerprint,
                "recovery_bucket_fingerprint": qualification.recovery_bucket_fingerprint,
                "candidate_storage_key_fingerprint": qualification.candidate_storage_key_fingerprint,
                "source_authority_fingerprint": qualification.source_authority_fingerprint,
                "candidate_authority_fingerprint": qualification.candidate_authority_fingerprint,
                "configuration_fingerprint": qualification.configuration_fingerprint,
                "verified_durable_read_count": qualification.verified_durable_read_count,
                "integrity_failure_count": qualification.integrity_failure_count,
                "storage_unavailable_count": qualification.storage_unavailable_count,
                "route_expired_attempt_count": qualification.route_expired_attempt_count,
                "operational_event_count": qualification.operational_event_count,
                "route_version": route.route_version,
                "route_class": route.route_class,
                "route_authority_kind": route.route_authority_kind,
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
        request_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "phase_t_health_qualification_id": str(qualification.id),
                "phase_t_health_qualification_hash": qualification.health_qualification_hash,
                "phase_t_health_receipt_hash": receipt.receipt_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "integrity_proof_hash": integrity_proof_hash,
                "route_version_at_request": route.route_version,
                "mode": "phase_u_read_ownership_transition_authorization",
                "routable_authority_created": False,
                "durable_read_route_created": False,
                "read_path_switched": False,
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return ReadOwnershipTransitionAuthorizationSnapshot(
            phase_t_health_qualification_id=qualification.id,
            phase_t_health_receipt_id=receipt.id,
            reauthorized_renewal_lease_id=qualification.reauthorized_renewal_lease_id,
            activation_receipt_id=qualification.activation_receipt_id,
            terminal_receipt_id=qualification.terminal_receipt_id,
            reauthorization_id=qualification.reauthorization_id,
            phase_q_health_qualification_id=qualification.phase_q_health_qualification_id,
            prior_renewal_lease_id=qualification.prior_renewal_lease_id,
            replica_id=qualification.replica_id,
            phase_t_health_qualification_hash=qualification.health_qualification_hash,
            phase_t_request_snapshot_hash=qualification.request_snapshot_hash,
            phase_t_health_receipt_hash=receipt.receipt_hash,
            operational_evidence_hash=qualification.operational_evidence_hash,
            health_state=qualification.health_state,
            reauthorized_renewal_lease_hash=qualification.reauthorized_renewal_lease_hash,
            lease_snapshot_hash=qualification.lease_snapshot_hash,
            activation_receipt_hash=qualification.activation_receipt_hash,
            terminal_receipt_hash=qualification.terminal_receipt_hash,
            reauthorization_hash=qualification.reauthorization_hash,
            phase_q_health_qualification_hash=qualification.phase_q_health_qualification_hash,
            prior_renewal_lease_hash=qualification.prior_renewal_lease_hash,
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
            phase_t_qualified_by_id=qualification.qualified_by_id,
            reauthorized_renewal_activated_by_id=lease.activated_by_id,
            reauthorization_approved_by_id=reauthorization.approved_by_id,
            phase_q_qualified_by_id=phase_q.qualified_by_id,
            prior_renewal_activated_by_id=prior_lease.activated_by_id,
        )
    except RecoveryReadOwnershipTransitionAuthorizationError:
        raise
    except RecoveryDurableReadReauthorizedRenewalHealthNotFound as exc:
        raise RecoveryReadOwnershipTransitionAuthorizationNotFound(str(exc)) from exc
    except RecoveryDurableReadReauthorizedRenewalHealthConflict as exc:
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(str(exc)) from exc
    except RecoveryDurableReadReauthorizedRenewalHealthUnavailable as exc:
        raise RecoveryReadOwnershipTransitionAuthorizationUnavailable(str(exc)) from exc


def _matches_snapshot(
    authorization: EvidenceRecoveryReadOwnershipTransitionAuthorization,
    snapshot: ReadOwnershipTransitionAuthorizationSnapshot,
) -> bool:
    return all(
        getattr(authorization, field) == getattr(snapshot, field)
        for field in ReadOwnershipTransitionAuthorizationSnapshot.__dataclass_fields__
    )


def _new_receipt(
    *,
    authorization: EvidenceRecoveryReadOwnershipTransitionAuthorization,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "phase_t_health_qualification_id": str(authorization.phase_t_health_qualification_id),
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
    return EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        authorization_id=authorization.id,
        phase_t_health_qualification_id=authorization.phase_t_health_qualification_id,
        reauthorized_renewal_lease_id=authorization.reauthorized_renewal_lease_id,
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
    authorization: EvidenceRecoveryReadOwnershipTransitionAuthorization,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt:
    authorization.status = phase
    authorization.terminal_by_id = actor_id
    authorization.terminal_at = now
    authorization.terminal_reason = reason
    receipt = _new_receipt(
        authorization=authorization,
        phase=phase,
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
) -> EvidenceRecoveryReadOwnershipTransitionAuthorization:
    stmt = select(EvidenceRecoveryReadOwnershipTransitionAuthorization).where(
        EvidenceRecoveryReadOwnershipTransitionAuthorization.id == authorization_id,
        EvidenceRecoveryReadOwnershipTransitionAuthorization.organization_id == organization_id,
        EvidenceRecoveryReadOwnershipTransitionAuthorization.claim_id == claim_id,
        EvidenceRecoveryReadOwnershipTransitionAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RecoveryReadOwnershipTransitionAuthorizationNotFound(
            "Read-ownership transition authorization not found"
        )
    return authorization


def request_read_ownership_transition_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    phase_t_health_qualification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadOwnershipTransitionAuthorization,
    EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Read-ownership transition authorization request reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    existing = db.scalar(
        select(EvidenceRecoveryReadOwnershipTransitionAuthorization)
        .where(
            EvidenceRecoveryReadOwnershipTransitionAuthorization.organization_id == organization_id,
            EvidenceRecoveryReadOwnershipTransitionAuthorization.phase_t_health_qualification_id
            == phase_t_health_qualification_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id != requested_by_id or existing.request_reason != normalized_reason:
            raise RecoveryReadOwnershipTransitionAuthorizationConflict(
                "Phase U request replay must use the original requester and reason"
            )
        if (
            existing.status == "pending_second_approval"
            and current_time >= _as_utc(existing.review_expires_at)
        ):
            receipt = _terminalize(
                db,
                authorization=existing,
                phase="expired",
                actor_id=requested_by_id,
                reason="Phase U second-approval window expired",
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
            phase_t_health_qualification_id=phase_t_health_qualification_id,
        )
        if not _matches_snapshot(existing, snapshot):
            receipt = _terminalize(
                db,
                authorization=existing,
                phase="invalidated",
                actor_id=requested_by_id,
                reason="Phase T authorization evidence drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_t_health_qualification_id=phase_t_health_qualification_id,
    )
    review_expires_at = current_time + READ_OWNERSHIP_REVIEW_WINDOW
    authorization_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "phase_t_health_qualification_id": str(snapshot.phase_t_health_qualification_id),
            "phase_t_health_qualification_hash": snapshot.phase_t_health_qualification_hash,
            "phase_t_health_receipt_hash": snapshot.phase_t_health_receipt_hash,
            "operational_evidence_hash": snapshot.operational_evidence_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "mode": "phase_u_read_ownership_transition_authorization",
        }
    )
    authorization = EvidenceRecoveryReadOwnershipTransitionAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        **{
            field: getattr(snapshot, field)
            for field in ReadOwnershipTransitionAuthorizationSnapshot.__dataclass_fields__
        },
        authorization_hash=authorization_hash,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        requested_at=current_time,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
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


def approve_read_ownership_transition_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadOwnershipTransitionAuthorization,
    EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Read-ownership transition approval reason is required"
        )
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
        return authorization, None, "unchanged"
    if authorization.status != "pending_second_approval":
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Only a pending Phase U authorization can be approved"
        )
    if current_time >= _as_utc(authorization.review_expires_at):
        receipt = _terminalize(
            db,
            authorization=authorization,
            phase="expired",
            actor_id=approved_by_id,
            reason="Phase U second-approval window expired",
            now=current_time,
        )
        return authorization, receipt, "expired"
    if approved_by_id in {
        authorization.requested_by_id,
        authorization.phase_t_qualified_by_id,
        authorization.reauthorized_renewal_activated_by_id,
        authorization.reauthorization_approved_by_id,
        authorization.phase_q_qualified_by_id,
        authorization.prior_renewal_activated_by_id,
    }:
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Phase U approver must be independent from the requester and prior qualification/routing actors"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_t_health_qualification_id=authorization.phase_t_health_qualification_id,
        )
    except RecoveryReadOwnershipTransitionAuthorizationUnavailable:
        raise
    except (
        RecoveryReadOwnershipTransitionAuthorizationNotFound,
        RecoveryReadOwnershipTransitionAuthorizationConflict,
    ) as exc:
        receipt = _terminalize(
            db,
            authorization=authorization,
            phase="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh Phase U preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return authorization, receipt, "invalidated"
    if not _matches_snapshot(authorization, snapshot):
        receipt = _terminalize(
            db,
            authorization=authorization,
            phase="invalidated",
            actor_id=approved_by_id,
            reason="Phase T snapshot drifted before Phase U second approval",
            now=current_time,
        )
        return authorization, receipt, "invalidated"

    authorization.status = "approved"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current_time
    authorization.authorization_expires_at = current_time + READ_OWNERSHIP_AUTHORIZATION_WINDOW
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


def reject_read_ownership_transition_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadOwnershipTransitionAuthorization,
    EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Read-ownership transition rejection reason is required"
        )
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
        return authorization, None, "unchanged"
    if authorization.status != "pending_second_approval":
        raise RecoveryReadOwnershipTransitionAuthorizationConflict(
            "Only a pending Phase U authorization can be rejected"
        )
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


def get_read_ownership_transition_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> EvidenceRecoveryReadOwnershipTransitionAuthorization:
    return _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )


def list_read_ownership_transition_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> list[EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt]:
    _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt)
            .where(
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.organization_id
                == organization_id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.authorization_id
                == authorization_id,
            )
            .order_by(
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.created_at.asc(),
            )
        ).all()
    )
