from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_read_health_models import (
    EvidenceRecoveryDurableReadHealthQualification,
    EvidenceRecoveryDurableReadHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_health_service import (
    RecoveryDurableReadHealthConflict,
    RecoveryDurableReadHealthNotFound,
    RecoveryDurableReadHealthUnavailable,
    _get_qualification as _get_health_qualification,
    _load_snapshot as _load_health_snapshot,
    _matches_snapshot as _matches_health_snapshot,
)
from app.modules.documents.recovery_durable_read_renewal_models import (
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

DURABLE_READ_RENEWAL_AUTHORIZATION_WINDOW = timedelta(minutes=10)


class RecoveryDurableReadRenewalAuthorizationError(RuntimeError):
    pass


class RecoveryDurableReadRenewalAuthorizationNotFound(
    RecoveryDurableReadRenewalAuthorizationError
):
    pass


class RecoveryDurableReadRenewalAuthorizationConflict(
    RecoveryDurableReadRenewalAuthorizationError
):
    pass


class RecoveryDurableReadRenewalAuthorizationUnavailable(
    RecoveryDurableReadRenewalAuthorizationError
):
    pass


@dataclass(frozen=True)
class DurableReadRenewalAuthorizationSnapshot:
    health_qualification_id: UUID
    health_qualification_receipt_id: UUID
    durable_lease_id: UUID
    activation_receipt_id: UUID
    terminal_receipt_id: UUID
    prior_authorization_id: UUID
    phase_k_qualification_id: UUID
    replica_id: UUID
    health_qualification_hash: str
    health_request_snapshot_hash: str
    health_qualification_receipt_hash: str
    operational_evidence_hash: str
    health_state: str
    durable_lease_hash: str
    lease_snapshot_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    prior_authorization_hash: str
    phase_k_qualification_hash: str
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
    route_version_at_request: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualified_by_id: UUID
    durable_activated_by_id: UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _health_qualification_receipt(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableReadHealthQualification,
) -> EvidenceRecoveryDurableReadHealthQualificationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadHealthQualificationReceipt).where(
                EvidenceRecoveryDurableReadHealthQualificationReceipt.organization_id
                == qualification.organization_id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.claim_id
                == qualification.claim_id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.document_id
                == qualification.document_id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.health_qualification_id
                == qualification.id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Qualified Phase N health evidence must have exactly one qualified receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.durable_lease_id == qualification.durable_lease_id,
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
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Phase N health qualification receipt lineage is inconsistent"
        )
    return receipt


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> DurableReadRenewalAuthorizationSnapshot:
    try:
        qualification = _get_health_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
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
            raise RecoveryDurableReadRenewalAuthorizationConflict(
                "Only qualified healthy Phase N operational evidence can request durable read renewal authorization"
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
            raise RecoveryDurableReadRenewalAuthorizationConflict(
                "Phase N qualification crossed its non-routable safety boundary"
            )

        health_snapshot = _load_health_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            durable_lease_id=qualification.durable_lease_id,
        )
        if not _matches_health_snapshot(qualification, health_snapshot):
            raise RecoveryDurableReadRenewalAuthorizationConflict(
                "Phase N operational-health lineage drifted before renewal authorization"
            )
        receipt = _health_qualification_receipt(db, qualification=qualification)
        route = health_snapshot.route
        if not all(
            (
                route.route_class == "local_source",
                route.route_authority_kind == "local",
                route.active_lease_id is None,
                route.active_durable_lease_id is None,
                route.active_replica_id is None,
                route.read_path_switched is False,
                route.write_path_switched is False,
                route.document_storage_key_mutated is False,
                route.authoritative_storage_changed is False,
                route.destructive_action_performed is False,
                route.route_version == qualification.route_version_at_request,
                route.source_authority_fingerprint
                == qualification.source_authority_fingerprint,
                route.candidate_authority_fingerprint
                == qualification.candidate_authority_fingerprint,
                route.configuration_fingerprint == qualification.configuration_fingerprint,
            )
        ):
            raise RecoveryDurableReadRenewalAuthorizationConflict(
                "Live read route changed after Phase N qualification"
            )

        integrity_proof_hash = _canonical_hash(
            {
                "health_qualification_id": str(qualification.id),
                "health_qualification_hash": qualification.health_qualification_hash,
                "health_qualification_receipt_id": str(receipt.id),
                "health_qualification_receipt_hash": receipt.receipt_hash,
                "durable_lease_id": str(qualification.durable_lease_id),
                "durable_lease_hash": qualification.durable_lease_hash,
                "activation_receipt_id": str(qualification.activation_receipt_id),
                "activation_receipt_hash": qualification.activation_receipt_hash,
                "terminal_receipt_id": str(qualification.terminal_receipt_id),
                "terminal_receipt_hash": qualification.terminal_receipt_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "health_state": qualification.health_state,
                "verified_durable_read_count": qualification.verified_durable_read_count,
                "integrity_failure_count": qualification.integrity_failure_count,
                "storage_unavailable_count": qualification.storage_unavailable_count,
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
                "health_qualification_id": str(qualification.id),
                "health_request_snapshot_hash": qualification.request_snapshot_hash,
                "operational_evidence_hash": qualification.operational_evidence_hash,
                "integrity_proof_hash": integrity_proof_hash,
                "route_version_at_request": route.route_version,
                "mode": "bounded_durable_read_renewal_governance_authorization_only",
                "routable_authority_created": False,
                "durable_read_route_created": False,
                "read_path_switched": False,
                "write_path_switched": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return DurableReadRenewalAuthorizationSnapshot(
            health_qualification_id=qualification.id,
            health_qualification_receipt_id=receipt.id,
            durable_lease_id=qualification.durable_lease_id,
            activation_receipt_id=qualification.activation_receipt_id,
            terminal_receipt_id=qualification.terminal_receipt_id,
            prior_authorization_id=qualification.authorization_id,
            phase_k_qualification_id=qualification.qualification_id,
            replica_id=qualification.replica_id,
            health_qualification_hash=qualification.health_qualification_hash,
            health_request_snapshot_hash=qualification.request_snapshot_hash,
            health_qualification_receipt_hash=receipt.receipt_hash,
            operational_evidence_hash=qualification.operational_evidence_hash,
            health_state=qualification.health_state,
            durable_lease_hash=qualification.durable_lease_hash,
            lease_snapshot_hash=qualification.lease_snapshot_hash,
            activation_receipt_hash=qualification.activation_receipt_hash,
            terminal_receipt_hash=qualification.terminal_receipt_hash,
            prior_authorization_hash=qualification.authorization_hash,
            phase_k_qualification_hash=qualification.phase_k_qualification_hash,
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
            route_version_at_request=route.route_version,
            integrity_proof_hash=integrity_proof_hash,
            request_snapshot_hash=request_snapshot_hash,
            health_qualified_by_id=qualification.qualified_by_id,
            durable_activated_by_id=qualification.activated_by_id,
        )
    except RecoveryDurableReadRenewalAuthorizationError:
        raise
    except RecoveryDurableReadHealthNotFound as exc:
        raise RecoveryDurableReadRenewalAuthorizationNotFound(str(exc)) from exc
    except RecoveryDurableReadHealthConflict as exc:
        raise RecoveryDurableReadRenewalAuthorizationConflict(str(exc)) from exc
    except RecoveryDurableReadHealthUnavailable as exc:
        raise RecoveryDurableReadRenewalAuthorizationUnavailable(str(exc)) from exc


def _matches_snapshot(
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization,
    snapshot: DurableReadRenewalAuthorizationSnapshot,
) -> bool:
    return all(
        (
            authorization.health_qualification_id == snapshot.health_qualification_id,
            authorization.health_qualification_receipt_id == snapshot.health_qualification_receipt_id,
            authorization.durable_lease_id == snapshot.durable_lease_id,
            authorization.activation_receipt_id == snapshot.activation_receipt_id,
            authorization.terminal_receipt_id == snapshot.terminal_receipt_id,
            authorization.prior_authorization_id == snapshot.prior_authorization_id,
            authorization.phase_k_qualification_id == snapshot.phase_k_qualification_id,
            authorization.replica_id == snapshot.replica_id,
            authorization.health_qualification_hash == snapshot.health_qualification_hash,
            authorization.health_request_snapshot_hash == snapshot.health_request_snapshot_hash,
            authorization.health_qualification_receipt_hash
            == snapshot.health_qualification_receipt_hash,
            authorization.operational_evidence_hash == snapshot.operational_evidence_hash,
            authorization.health_state == snapshot.health_state,
            authorization.durable_lease_hash == snapshot.durable_lease_hash,
            authorization.lease_snapshot_hash == snapshot.lease_snapshot_hash,
            authorization.activation_receipt_hash == snapshot.activation_receipt_hash,
            authorization.terminal_receipt_hash == snapshot.terminal_receipt_hash,
            authorization.prior_authorization_hash == snapshot.prior_authorization_hash,
            authorization.phase_k_qualification_hash == snapshot.phase_k_qualification_hash,
            authorization.replica_hash == snapshot.replica_hash,
            authorization.source_file_hash == snapshot.source_file_hash,
            authorization.source_file_size_bytes == snapshot.source_file_size_bytes,
            authorization.local_storage_key_fingerprint == snapshot.local_storage_key_fingerprint,
            authorization.recovery_bucket_fingerprint == snapshot.recovery_bucket_fingerprint,
            authorization.candidate_storage_key_fingerprint
            == snapshot.candidate_storage_key_fingerprint,
            authorization.source_authority_fingerprint == snapshot.source_authority_fingerprint,
            authorization.candidate_authority_fingerprint
            == snapshot.candidate_authority_fingerprint,
            authorization.configuration_fingerprint == snapshot.configuration_fingerprint,
            authorization.verified_durable_read_count == snapshot.verified_durable_read_count,
            authorization.integrity_failure_count == snapshot.integrity_failure_count,
            authorization.storage_unavailable_count == snapshot.storage_unavailable_count,
            authorization.route_version_at_request == snapshot.route_version_at_request,
            authorization.integrity_proof_hash == snapshot.integrity_proof_hash,
            authorization.request_snapshot_hash == snapshot.request_snapshot_hash,
            authorization.health_qualified_by_id == snapshot.health_qualified_by_id,
            authorization.durable_activated_by_id == snapshot.durable_activated_by_id,
        )
    )


def _new_receipt(
    *,
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadRenewalAuthorizationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "health_qualification_id": str(authorization.health_qualification_id),
            "durable_lease_id": str(authorization.durable_lease_id),
            "phase": phase,
            "health_qualification_hash": authorization.health_qualification_hash,
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
    return EvidenceRecoveryDurableReadRenewalAuthorizationReceipt(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        authorization_id=authorization.id,
        health_qualification_id=authorization.health_qualification_id,
        durable_lease_id=authorization.durable_lease_id,
        phase=phase,
        health_qualification_hash=authorization.health_qualification_hash,
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
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadRenewalAuthorizationReceipt:
    authorization.status = status
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


def request_durable_read_renewal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Durable read renewal authorization request reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalAuthorization)
        .where(
            EvidenceRecoveryDurableReadRenewalAuthorization.organization_id == organization_id,
            EvidenceRecoveryDurableReadRenewalAuthorization.claim_id == claim_id,
            EvidenceRecoveryDurableReadRenewalAuthorization.document_id == document_id,
            EvidenceRecoveryDurableReadRenewalAuthorization.health_qualification_id
            == health_qualification_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if not _matches_snapshot(existing, snapshot):
            if existing.status == "pending_second_approval":
                receipt = _terminalize(
                    db,
                    authorization=existing,
                    status="invalidated",
                    actor_id=requested_by_id,
                    reason="Durable read renewal authorization lineage drifted before request replay",
                    now=current_time,
                )
                return existing, receipt, "invalidated"
            raise RecoveryDurableReadRenewalAuthorizationConflict(
                "Existing durable read renewal authorization no longer matches the current evidence snapshot"
            )
        if not (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
        ):
            raise RecoveryDurableReadRenewalAuthorizationConflict(
                "A renewal authorization already exists for this health qualification with different request semantics"
            )
        return existing, None, "unchanged"

    authorization_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "health_qualification_id": str(health_qualification_id),
            "health_qualification_hash": snapshot.health_qualification_hash,
            "operational_evidence_hash": snapshot.operational_evidence_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "request_reason": normalized_reason,
            "mode": "non_routable_bounded_durable_read_renewal_authorization",
        }
    )
    authorization = EvidenceRecoveryDurableReadRenewalAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=snapshot.health_qualification_id,
        health_qualification_receipt_id=snapshot.health_qualification_receipt_id,
        durable_lease_id=snapshot.durable_lease_id,
        activation_receipt_id=snapshot.activation_receipt_id,
        terminal_receipt_id=snapshot.terminal_receipt_id,
        prior_authorization_id=snapshot.prior_authorization_id,
        phase_k_qualification_id=snapshot.phase_k_qualification_id,
        replica_id=snapshot.replica_id,
        health_qualification_hash=snapshot.health_qualification_hash,
        health_request_snapshot_hash=snapshot.health_request_snapshot_hash,
        health_qualification_receipt_hash=snapshot.health_qualification_receipt_hash,
        operational_evidence_hash=snapshot.operational_evidence_hash,
        health_state=snapshot.health_state,
        durable_lease_hash=snapshot.durable_lease_hash,
        lease_snapshot_hash=snapshot.lease_snapshot_hash,
        activation_receipt_hash=snapshot.activation_receipt_hash,
        terminal_receipt_hash=snapshot.terminal_receipt_hash,
        prior_authorization_hash=snapshot.prior_authorization_hash,
        phase_k_qualification_hash=snapshot.phase_k_qualification_hash,
        replica_hash=snapshot.replica_hash,
        source_file_hash=snapshot.source_file_hash,
        source_file_size_bytes=snapshot.source_file_size_bytes,
        local_storage_key_fingerprint=snapshot.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=snapshot.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=snapshot.candidate_storage_key_fingerprint,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        verified_durable_read_count=snapshot.verified_durable_read_count,
        integrity_failure_count=snapshot.integrity_failure_count,
        storage_unavailable_count=snapshot.storage_unavailable_count,
        route_version_at_request=snapshot.route_version_at_request,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        authorization_hash=authorization_hash,
        health_qualified_by_id=snapshot.health_qualified_by_id,
        durable_activated_by_id=snapshot.durable_activated_by_id,
        status="pending_second_approval",
        authorization_expires_at=current_time + DURABLE_READ_RENEWAL_AUTHORIZATION_WINDOW,
        requested_by_id=requested_by_id,
        requested_at=current_time,
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


def reject_durable_read_renewal_authorization(
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
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Durable read renewal authorization rejection reason is required"
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
        if (
            authorization.rejected_by_id == rejected_by_id
            and authorization.rejection_reason == normalized_reason
        ):
            return authorization, None, "unchanged"
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Rejected renewal authorization replay does not match the original rejection"
        )
    if authorization.status != "pending_second_approval":
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Only a pending durable read renewal authorization can be rejected"
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


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDurableReadRenewalAuthorization:
    stmt = select(EvidenceRecoveryDurableReadRenewalAuthorization).where(
        EvidenceRecoveryDurableReadRenewalAuthorization.id == authorization_id,
        EvidenceRecoveryDurableReadRenewalAuthorization.organization_id == organization_id,
        EvidenceRecoveryDurableReadRenewalAuthorization.claim_id == claim_id,
        EvidenceRecoveryDurableReadRenewalAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RecoveryDurableReadRenewalAuthorizationNotFound(
            "Recovery durable read renewal authorization not found"
        )
    return authorization


def get_durable_read_renewal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> EvidenceRecoveryDurableReadRenewalAuthorization:
    return _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )


def list_durable_read_renewal_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> list[EvidenceRecoveryDurableReadRenewalAuthorizationReceipt]:
    _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalAuthorizationReceipt)
            .where(
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.organization_id
                == organization_id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.authorization_id
                == authorization_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.id.asc(),
            )
        ).all()
    )
