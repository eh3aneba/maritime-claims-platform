from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathCutoverReceipt,
    EvidenceRecoveryReadPathRoute,
)
from app.modules.documents.recovery_routable_read_qualification_models import (
    EvidenceRecoveryRoutableReadQualification,
    EvidenceRecoveryRoutableReadQualificationReceipt,
)


class RecoveryRoutableReadQualificationError(RuntimeError):
    pass


class RecoveryRoutableReadQualificationNotFound(RecoveryRoutableReadQualificationError):
    pass


class RecoveryRoutableReadQualificationConflict(RecoveryRoutableReadQualificationError):
    pass


@dataclass(frozen=True)
class SuccessfulReadCutoverCycle:
    lease: EvidenceRecoveryReadPathCutoverLease
    activation: EvidenceRecoveryReadPathCutoverReceipt
    rollback: EvidenceRecoveryReadPathCutoverReceipt
    cycle_proof_hash: str


@dataclass(frozen=True)
class RoutableReadQualificationSnapshot:
    first: SuccessfulReadCutoverCycle
    second: SuccessfulReadCutoverCycle
    replica_id: UUID
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    route_version_at_request: int
    qualification_bundle_hash: str
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _get_cutover_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryReadPathCutoverLease:
    lease = db.scalar(
        select(EvidenceRecoveryReadPathCutoverLease).where(
            EvidenceRecoveryReadPathCutoverLease.id == lease_id,
            EvidenceRecoveryReadPathCutoverLease.organization_id == organization_id,
            EvidenceRecoveryReadPathCutoverLease.claim_id == claim_id,
            EvidenceRecoveryReadPathCutoverLease.document_id == document_id,
        )
    )
    if lease is None:
        raise RecoveryRoutableReadQualificationNotFound(
            "Recovery read-path cutover lease not found"
        )
    return lease


def _get_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> EvidenceRecoveryReadPathRoute:
    route = db.scalar(
        select(EvidenceRecoveryReadPathRoute).where(
            EvidenceRecoveryReadPathRoute.organization_id == organization_id,
            EvidenceRecoveryReadPathRoute.claim_id == claim_id,
            EvidenceRecoveryReadPathRoute.document_id == document_id,
        )
    )
    if route is None:
        raise RecoveryRoutableReadQualificationNotFound(
            "Recovery read-path route not found"
        )
    return route


def _cutover_receipt(
    db: Session,
    *,
    lease: EvidenceRecoveryReadPathCutoverLease,
    phase: str,
) -> EvidenceRecoveryReadPathCutoverReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryReadPathCutoverReceipt).where(
                EvidenceRecoveryReadPathCutoverReceipt.organization_id
                == lease.organization_id,
                EvidenceRecoveryReadPathCutoverReceipt.claim_id == lease.claim_id,
                EvidenceRecoveryReadPathCutoverReceipt.document_id == lease.document_id,
                EvidenceRecoveryReadPathCutoverReceipt.cutover_lease_id == lease.id,
                EvidenceRecoveryReadPathCutoverReceipt.phase == phase,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryRoutableReadQualificationConflict(
            f"Cutover lease must have exactly one {phase} receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.authorization_id == lease.authorization_id,
            receipt.lease_snapshot_hash == lease.lease_snapshot_hash,
            receipt.lease_hash == lease.lease_hash,
            receipt.authorization_hash == lease.authorization_hash,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
        )
    ):
        raise RecoveryRoutableReadQualificationConflict(
            "Cutover receipt lineage is inconsistent"
        )
    return receipt


def _load_successful_cycle(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> SuccessfulReadCutoverCycle:
    lease = _get_cutover_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    if lease.status != "rolled_back":
        raise RecoveryRoutableReadQualificationConflict(
            "Only a successfully rolled-back routable read cutover can qualify"
        )
    if (
        lease.activated_by_id is None
        or lease.activated_at is None
        or lease.rolled_back_by_id is None
        or lease.rolled_back_at is None
    ):
        raise RecoveryRoutableReadQualificationConflict(
            "Rolled-back cutover lease is missing activation or rollback lineage"
        )
    if any(
        (
            lease.routable_authority_created,
            lease.read_path_switched,
            lease.write_path_switched,
            lease.document_storage_key_mutated,
            lease.authoritative_storage_changed,
            lease.destructive_action_performed,
            lease.s3_delete_performed,
            lease.local_delete_performed,
        )
    ):
        raise RecoveryRoutableReadQualificationConflict(
            "Rolled-back cutover lease did not return to the non-destructive local boundary"
        )

    activation = _cutover_receipt(db, lease=lease, phase="activated")
    rollback = _cutover_receipt(db, lease=lease, phase="rolled_back")
    if not all(
        (
            activation.from_route_class == "local_source",
            activation.to_route_class == "recovery_replica",
            activation.routable_authority_created is True,
            activation.read_path_switched is True,
            activation.actor_id == lease.activated_by_id,
            _as_utc(activation.transitioned_at) == _as_utc(lease.activated_at),
            rollback.from_route_class == "recovery_replica",
            rollback.to_route_class == "local_source",
            rollback.routable_authority_created is False,
            rollback.read_path_switched is False,
            rollback.actor_id == lease.rolled_back_by_id,
            _as_utc(rollback.transitioned_at) == _as_utc(lease.rolled_back_at),
            rollback.route_version == activation.route_version + 1,
        )
    ):
        raise RecoveryRoutableReadQualificationConflict(
            "Cutover activation/rollback transition proof is inconsistent"
        )

    cycle_proof_hash = _canonical_hash(
        {
            "cutover_lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "authorization_hash": lease.authorization_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "activation_actor_id": str(activation.actor_id),
            "activation_at": _utc_iso(_as_utc(activation.transitioned_at)),
            "activation_route_version": activation.route_version,
            "rollback_receipt_id": str(rollback.id),
            "rollback_receipt_hash": rollback.receipt_hash,
            "rollback_actor_id": str(rollback.actor_id),
            "rollback_at": _utc_iso(_as_utc(rollback.transitioned_at)),
            "rollback_route_version": rollback.route_version,
            "replica_id": str(lease.replica_id),
            "replica_hash": lease.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "rolled_back_to_local_source": True,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    return SuccessfulReadCutoverCycle(
        lease=lease,
        activation=activation,
        rollback=rollback,
        cycle_proof_hash=cycle_proof_hash,
    )


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    cutover_lease_ids: list[UUID] | tuple[UUID, UUID],
) -> RoutableReadQualificationSnapshot:
    if len(cutover_lease_ids) != 2 or len(set(cutover_lease_ids)) != 2:
        raise RecoveryRoutableReadQualificationConflict(
            "Exactly two distinct routable read cutover leases are required"
        )

    cycles = [
        _load_successful_cycle(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
        for lease_id in cutover_lease_ids
    ]
    cycles.sort(
        key=lambda item: (
            _as_utc(item.lease.rolled_back_at),
            str(item.lease.id),
        )
    )
    first, second = cycles
    if first.lease.authorization_id == second.lease.authorization_id:
        raise RecoveryRoutableReadQualificationConflict(
            "Repeated qualification requires independently authorized cutover leases"
        )

    lineage_fields = (
        "replica_id",
        "replica_hash",
        "source_file_hash",
        "source_file_size_bytes",
        "recovery_bucket_fingerprint",
        "candidate_storage_key_fingerprint",
        "source_authority_fingerprint",
        "candidate_authority_fingerprint",
        "configuration_fingerprint",
    )
    if any(
        getattr(first.lease, field) != getattr(second.lease, field)
        for field in lineage_fields
    ):
        raise RecoveryRoutableReadQualificationConflict(
            "Qualifying cutovers do not share one exact recovery evidence lineage"
        )

    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    if not all(
        (
            route.route_class == "local_source",
            route.active_lease_id is None,
            route.active_replica_id is None,
            route.read_path_switched is False,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.source_authority_fingerprint
            == first.lease.source_authority_fingerprint,
            route.candidate_authority_fingerprint
            == first.lease.candidate_authority_fingerprint,
            route.configuration_fingerprint == first.lease.configuration_fingerprint,
            route.route_version >= first.rollback.route_version,
            route.route_version >= second.rollback.route_version,
        )
    ):
        raise RecoveryRoutableReadQualificationConflict(
            "Live read route is not in the clean local-source rollback state"
        )

    qualification_bundle_hash = _canonical_hash(
        {
            "document_id": str(document_id),
            "replica_id": str(first.lease.replica_id),
            "successful_cycle_count": 2,
            "cycles": [
                {
                    "cutover_lease_id": str(first.lease.id),
                    "authorization_id": str(first.lease.authorization_id),
                    "lease_hash": first.lease.lease_hash,
                    "cycle_proof_hash": first.cycle_proof_hash,
                },
                {
                    "cutover_lease_id": str(second.lease.id),
                    "authorization_id": str(second.lease.authorization_id),
                    "lease_hash": second.lease.lease_hash,
                    "cycle_proof_hash": second.cycle_proof_hash,
                },
            ],
        }
    )
    request_snapshot_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "qualification_bundle_hash": qualification_bundle_hash,
            "replica_hash": first.lease.replica_hash,
            "source_file_hash": first.lease.source_file_hash,
            "source_file_size_bytes": first.lease.source_file_size_bytes,
            "recovery_bucket_fingerprint": first.lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": first.lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": first.lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": first.lease.candidate_authority_fingerprint,
            "configuration_fingerprint": first.lease.configuration_fingerprint,
            "route_class": route.route_class,
            "route_version": route.route_version,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "mode": "repeated_routable_read_cutover_qualification_only",
        }
    )
    return RoutableReadQualificationSnapshot(
        first=first,
        second=second,
        replica_id=first.lease.replica_id,
        replica_hash=first.lease.replica_hash,
        source_file_hash=first.lease.source_file_hash,
        source_file_size_bytes=first.lease.source_file_size_bytes,
        recovery_bucket_fingerprint=first.lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=first.lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=first.lease.source_authority_fingerprint,
        candidate_authority_fingerprint=first.lease.candidate_authority_fingerprint,
        configuration_fingerprint=first.lease.configuration_fingerprint,
        route_version_at_request=route.route_version,
        qualification_bundle_hash=qualification_bundle_hash,
        request_snapshot_hash=request_snapshot_hash,
    )


def _matches_snapshot(
    qualification: EvidenceRecoveryRoutableReadQualification,
    snapshot: RoutableReadQualificationSnapshot,
) -> bool:
    return all(
        (
            qualification.first_cutover_lease_id == snapshot.first.lease.id,
            qualification.second_cutover_lease_id == snapshot.second.lease.id,
            qualification.first_authorization_id == snapshot.first.lease.authorization_id,
            qualification.second_authorization_id == snapshot.second.lease.authorization_id,
            qualification.first_activation_receipt_id == snapshot.first.activation.id,
            qualification.first_rollback_receipt_id == snapshot.first.rollback.id,
            qualification.second_activation_receipt_id == snapshot.second.activation.id,
            qualification.second_rollback_receipt_id == snapshot.second.rollback.id,
            qualification.first_lease_hash == snapshot.first.lease.lease_hash,
            qualification.second_lease_hash == snapshot.second.lease.lease_hash,
            qualification.first_activation_receipt_hash == snapshot.first.activation.receipt_hash,
            qualification.first_rollback_receipt_hash == snapshot.first.rollback.receipt_hash,
            qualification.second_activation_receipt_hash == snapshot.second.activation.receipt_hash,
            qualification.second_rollback_receipt_hash == snapshot.second.rollback.receipt_hash,
            qualification.first_cycle_proof_hash == snapshot.first.cycle_proof_hash,
            qualification.second_cycle_proof_hash == snapshot.second.cycle_proof_hash,
            qualification.qualification_bundle_hash == snapshot.qualification_bundle_hash,
            qualification.replica_id == snapshot.replica_id,
            qualification.replica_hash == snapshot.replica_hash,
            qualification.source_file_hash == snapshot.source_file_hash,
            qualification.source_file_size_bytes == snapshot.source_file_size_bytes,
            qualification.recovery_bucket_fingerprint == snapshot.recovery_bucket_fingerprint,
            qualification.candidate_storage_key_fingerprint
            == snapshot.candidate_storage_key_fingerprint,
            qualification.source_authority_fingerprint
            == snapshot.source_authority_fingerprint,
            qualification.candidate_authority_fingerprint
            == snapshot.candidate_authority_fingerprint,
            qualification.configuration_fingerprint == snapshot.configuration_fingerprint,
            qualification.route_version_at_request == snapshot.route_version_at_request,
            qualification.request_snapshot_hash == snapshot.request_snapshot_hash,
            qualification.first_activated_by_id == snapshot.first.lease.activated_by_id,
            qualification.second_activated_by_id == snapshot.second.lease.activated_by_id,
        )
    )


def _new_receipt(
    *,
    qualification: EvidenceRecoveryRoutableReadQualification,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryRoutableReadQualificationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "qualification_id": str(qualification.id),
            "phase": phase,
            "qualification_bundle_hash": qualification.qualification_bundle_hash,
            "request_snapshot_hash": qualification.request_snapshot_hash,
            "qualification_hash": qualification.qualification_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryRoutableReadQualificationReceipt(
        organization_id=qualification.organization_id,
        claim_id=qualification.claim_id,
        document_id=qualification.document_id,
        qualification_id=qualification.id,
        phase=phase,
        qualification_bundle_hash=qualification.qualification_bundle_hash,
        request_snapshot_hash=qualification.request_snapshot_hash,
        qualification_hash=qualification.qualification_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )


def _terminalize_invalidated(
    db: Session,
    *,
    qualification: EvidenceRecoveryRoutableReadQualification,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryRoutableReadQualificationReceipt:
    qualification.status = "invalidated"
    qualification.terminal_by_id = actor_id
    qualification.terminal_at = now
    qualification.terminal_reason = reason
    receipt = _new_receipt(
        qualification=qualification,
        phase="invalidated",
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_routable_read_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    cutover_lease_ids: list[UUID],
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryRoutableReadQualification,
    EvidenceRecoveryRoutableReadQualificationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableReadQualificationConflict(
            "Qualification request reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        cutover_lease_ids=cutover_lease_ids,
    )
    existing = db.scalar(
        select(EvidenceRecoveryRoutableReadQualification)
        .where(
            EvidenceRecoveryRoutableReadQualification.organization_id == organization_id,
            EvidenceRecoveryRoutableReadQualification.document_id == document_id,
            EvidenceRecoveryRoutableReadQualification.qualification_bundle_hash
            == snapshot.qualification_bundle_hash,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.status == "pending_second_approval" and not _matches_snapshot(
            existing, snapshot
        ):
            receipt = _terminalize_invalidated(
                db,
                qualification=existing,
                actor_id=requested_by_id,
                reason="Repeated read cutover qualification lineage drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    qualification_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "qualification_bundle_hash": snapshot.qualification_bundle_hash,
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "request_reason": normalized_reason,
            "mode": "non_routable_repeated_read_cutover_qualification",
        }
    )
    qualification = EvidenceRecoveryRoutableReadQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        replica_id=snapshot.replica_id,
        first_cutover_lease_id=snapshot.first.lease.id,
        second_cutover_lease_id=snapshot.second.lease.id,
        first_authorization_id=snapshot.first.lease.authorization_id,
        second_authorization_id=snapshot.second.lease.authorization_id,
        first_activation_receipt_id=snapshot.first.activation.id,
        first_rollback_receipt_id=snapshot.first.rollback.id,
        second_activation_receipt_id=snapshot.second.activation.id,
        second_rollback_receipt_id=snapshot.second.rollback.id,
        first_lease_hash=snapshot.first.lease.lease_hash,
        second_lease_hash=snapshot.second.lease.lease_hash,
        first_activation_receipt_hash=snapshot.first.activation.receipt_hash,
        first_rollback_receipt_hash=snapshot.first.rollback.receipt_hash,
        second_activation_receipt_hash=snapshot.second.activation.receipt_hash,
        second_rollback_receipt_hash=snapshot.second.rollback.receipt_hash,
        first_cycle_proof_hash=snapshot.first.cycle_proof_hash,
        second_cycle_proof_hash=snapshot.second.cycle_proof_hash,
        qualification_bundle_hash=snapshot.qualification_bundle_hash,
        replica_hash=snapshot.replica_hash,
        source_file_hash=snapshot.source_file_hash,
        source_file_size_bytes=snapshot.source_file_size_bytes,
        recovery_bucket_fingerprint=snapshot.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=snapshot.candidate_storage_key_fingerprint,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        route_version_at_request=snapshot.route_version_at_request,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        qualification_hash=qualification_hash,
        successful_cycle_count=2,
        first_activated_by_id=snapshot.first.lease.activated_by_id,
        second_activated_by_id=snapshot.second.lease.activated_by_id,
        requested_by_id=requested_by_id,
        requested_at=current_time,
        request_reason=normalized_reason,
        status="pending_second_approval",
        routable_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(qualification)
    db.flush()
    receipt = _new_receipt(
        qualification=qualification,
        phase="requested",
        actor_id=requested_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return qualification, receipt, "pending_second_approval"


def qualify_routable_read_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    qualified_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryRoutableReadQualification,
    EvidenceRecoveryRoutableReadQualificationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableReadQualificationConflict(
            "Qualification approval reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    qualification = _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
        for_update=True,
    )
    if qualification.status == "qualified":
        return qualification, None, "unchanged"
    if qualification.status != "pending_second_approval":
        raise RecoveryRoutableReadQualificationConflict(
            "Only a pending qualification can be approved"
        )
    if qualification.requested_by_id == qualified_by_id:
        raise RecoveryRoutableReadQualificationConflict(
            "Qualification requires a different Admin from the requester"
        )
    if qualified_by_id in {
        qualification.first_activated_by_id,
        qualification.second_activated_by_id,
    }:
        raise RecoveryRoutableReadQualificationConflict(
            "Qualification approver must differ from both cutover activators"
        )

    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            cutover_lease_ids=[
                qualification.first_cutover_lease_id,
                qualification.second_cutover_lease_id,
            ],
        )
    except (
        RecoveryRoutableReadQualificationNotFound,
        RecoveryRoutableReadQualificationConflict,
    ) as exc:
        receipt = _terminalize_invalidated(
            db,
            qualification=qualification,
            actor_id=qualified_by_id,
            reason=f"Fresh repeated read cutover qualification preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return qualification, receipt, "invalidated"
    if not _matches_snapshot(qualification, snapshot):
        receipt = _terminalize_invalidated(
            db,
            qualification=qualification,
            actor_id=qualified_by_id,
            reason="Repeated read cutover qualification snapshot drifted before approval",
            now=current_time,
        )
        return qualification, receipt, "invalidated"

    qualification.status = "qualified"
    qualification.qualified_by_id = qualified_by_id
    qualification.qualified_at = current_time
    qualification.qualification_reason = normalized_reason
    receipt = _new_receipt(
        qualification=qualification,
        phase="qualified",
        actor_id=qualified_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return qualification, receipt, "qualified"


def reject_routable_read_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryRoutableReadQualification,
    EvidenceRecoveryRoutableReadQualificationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableReadQualificationConflict(
            "Qualification rejection reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    qualification = _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
        for_update=True,
    )
    if qualification.status == "rejected":
        return qualification, None, "unchanged"
    if qualification.status != "pending_second_approval":
        raise RecoveryRoutableReadQualificationConflict(
            "Only a pending qualification can be rejected"
        )
    qualification.status = "rejected"
    qualification.rejected_by_id = rejected_by_id
    qualification.rejected_at = current_time
    qualification.rejection_reason = normalized_reason
    receipt = _new_receipt(
        qualification=qualification,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return qualification, receipt, "rejected"


def _get_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryRoutableReadQualification:
    stmt = select(EvidenceRecoveryRoutableReadQualification).where(
        EvidenceRecoveryRoutableReadQualification.id == qualification_id,
        EvidenceRecoveryRoutableReadQualification.organization_id == organization_id,
        EvidenceRecoveryRoutableReadQualification.claim_id == claim_id,
        EvidenceRecoveryRoutableReadQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    qualification = db.scalar(stmt)
    if qualification is None:
        raise RecoveryRoutableReadQualificationNotFound(
            "Recovery routable read qualification not found"
        )
    return qualification


def get_routable_read_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
) -> EvidenceRecoveryRoutableReadQualification:
    return _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
    )


def list_routable_read_qualification_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
) -> list[EvidenceRecoveryRoutableReadQualificationReceipt]:
    _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryRoutableReadQualificationReceipt)
            .where(
                EvidenceRecoveryRoutableReadQualificationReceipt.organization_id
                == organization_id,
                EvidenceRecoveryRoutableReadQualificationReceipt.claim_id == claim_id,
                EvidenceRecoveryRoutableReadQualificationReceipt.document_id == document_id,
                EvidenceRecoveryRoutableReadQualificationReceipt.qualification_id
                == qualification_id,
            )
            .order_by(
                EvidenceRecoveryRoutableReadQualificationReceipt.transitioned_at.asc(),
                EvidenceRecoveryRoutableReadQualificationReceipt.created_at.asc(),
                EvidenceRecoveryRoutableReadQualificationReceipt.id.asc(),
            )
        ).all()
    )
