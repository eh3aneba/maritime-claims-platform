from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_ownership_transition_authorization_models import (
    EvidenceRecoveryReadOwnershipTransitionAuthorization,
    EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt,
)
from app.modules.documents.recovery_read_ownership_transition_authorization_service import (
    RecoveryReadOwnershipTransitionAuthorizationConflict,
    RecoveryReadOwnershipTransitionAuthorizationNotFound,
    RecoveryReadOwnershipTransitionAuthorizationUnavailable,
    _get_authorization,
    _load_snapshot as _load_authorization_snapshot,
    _matches_snapshot as _matches_authorization_snapshot,
)
from app.modules.documents.recovery_read_ownership_transition_routing_models import (
    EvidenceRecoveryReadOwnershipTransitionLease,
    EvidenceRecoveryReadOwnershipTransitionReceipt,
)
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationUnavailable,
    _assert_replica_matches_source,
    _snapshot_local,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import (
    RecoveryRoutableReadCutoverConflict,
    RecoveryRoutableReadCutoverNotFound,
    RecoveryRoutableReadCutoverUnavailable,
    _get_route,
    _load_document,
    _load_replica,
    _read_verified_candidate,
)

READ_OWNERSHIP_TRANSITION_ROUTE_WINDOW = timedelta(hours=72)


class RecoveryReadOwnershipTransitionRoutingError(RuntimeError):
    pass


class RecoveryReadOwnershipTransitionRoutingNotFound(RecoveryReadOwnershipTransitionRoutingError):
    pass


class RecoveryReadOwnershipTransitionRoutingConflict(RecoveryReadOwnershipTransitionRoutingError):
    pass


class RecoveryReadOwnershipTransitionRoutingUnavailable(RecoveryReadOwnershipTransitionRoutingError):
    pass


@dataclass(frozen=True)
class ReadOwnershipTransitionRoutingSnapshot:
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_t_health_qualification_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_integrity_proof_hash: str
    authorization_approval_receipt_hash: str
    phase_t_health_qualification_hash: str
    operational_evidence_hash: str
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
    route_version_at_prepare: int
    integrity_proof_hash: str
    lease_snapshot_hash: str
    authorization_approved_by_id: UUID
    authorization_expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _route_is_clean_local(route: EvidenceRecoveryReadPathRoute) -> bool:
    return all(
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
        )
    )


def _approval_receipt(
    db: Session,
    *,
    authorization: EvidenceRecoveryReadOwnershipTransitionAuthorization,
) -> EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt).where(
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.organization_id
                == authorization.organization_id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.claim_id
                == authorization.claim_id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.document_id
                == authorization.document_id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.authorization_id
                == authorization.id,
                EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Approved Phase U authorization must have exactly one approval receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.phase_t_health_qualification_id == authorization.phase_t_health_qualification_id,
            receipt.reauthorized_renewal_lease_id == authorization.reauthorized_renewal_lease_id,
            receipt.health_state == authorization.health_state == "healthy",
            receipt.operational_evidence_hash == authorization.operational_evidence_hash,
            receipt.integrity_proof_hash == authorization.integrity_proof_hash,
            receipt.request_snapshot_hash == authorization.request_snapshot_hash,
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.actor_id == authorization.approved_by_id,
            authorization.approved_at is not None,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
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
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Phase U approval receipt lineage is inconsistent"
        )
    return receipt


def _fresh_source_and_candidate_proof(
    db: Session,
    *,
    authorization: EvidenceRecoveryReadOwnershipTransitionAuthorization,
) -> tuple[str, bytes]:
    document = _load_document(
        db,
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
    )
    replica = _load_replica(
        db,
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        replica_id=authorization.replica_id,
    )
    local_snapshot = _snapshot_local(document)
    _assert_replica_matches_source(replica, local_snapshot)
    candidate_payload = _read_verified_candidate(replica)
    if not all(
        (
            local_snapshot.file_hash == authorization.source_file_hash,
            local_snapshot.file_size_bytes == authorization.source_file_size_bytes,
            local_snapshot.storage_key_fingerprint == authorization.local_storage_key_fingerprint,
            replica.replica_hash == authorization.replica_hash,
            replica.recovery_bucket_fingerprint == authorization.recovery_bucket_fingerprint,
            hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
            == authorization.candidate_storage_key_fingerprint,
            hashlib.sha256(candidate_payload).hexdigest() == authorization.source_file_hash,
            len(candidate_payload) == authorization.source_file_size_bytes,
        )
    ):
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Fresh local or recovery candidate integrity does not match Phase U"
        )
    proof = _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "phase_t_health_qualification_id": str(authorization.phase_t_health_qualification_id),
            "replica_id": str(authorization.replica_id),
            "source_file_hash": authorization.source_file_hash,
            "source_file_size_bytes": authorization.source_file_size_bytes,
            "local_storage_key_fingerprint": authorization.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": authorization.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": authorization.candidate_storage_key_fingerprint,
            "candidate_payload_hash": hashlib.sha256(candidate_payload).hexdigest(),
            "candidate_payload_size": len(candidate_payload),
        }
    )
    return proof, candidate_payload


def _load_preparation_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
) -> ReadOwnershipTransitionRoutingSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        authorization = _get_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
        if not all(
            (
                authorization.status == "approved",
                authorization.approved_by_id is not None,
                authorization.approved_at is not None,
                authorization.authorization_expires_at is not None,
                authorization.health_state == "healthy",
                authorization.verified_durable_read_count >= 1,
                authorization.integrity_failure_count == 0,
                authorization.storage_unavailable_count == 0,
            )
        ):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Only an approved healthy Phase U authorization can prepare Phase V"
            )
        if current_time >= _as_utc(authorization.authorization_expires_at):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Approved Phase U authorization is outside its consumption window"
            )
        if any(
            (
                authorization.routable_authority_created,
                authorization.durable_read_route_created,
                authorization.read_path_switched,
                authorization.write_path_switched,
                authorization.document_storage_key_mutated,
                authorization.authoritative_storage_changed,
                authorization.destructive_action_performed,
                authorization.s3_delete_performed,
                authorization.local_delete_performed,
            )
        ):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U authorization crossed its non-routable safety boundary"
            )
        authorization_snapshot = _load_authorization_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_t_health_qualification_id=authorization.phase_t_health_qualification_id,
        )
        if not _matches_authorization_snapshot(authorization, authorization_snapshot):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U authorization lineage drifted before Phase V preparation"
            )
        approval = _approval_receipt(db, authorization=authorization)
        route = _get_route(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        assert route is not None
        if not (
            _route_is_clean_local(route)
            and route.route_version == authorization.route_version_at_request
            and route.source_authority_fingerprint == authorization.source_authority_fingerprint
            and route.candidate_authority_fingerprint == authorization.candidate_authority_fingerprint
            and route.configuration_fingerprint == authorization.configuration_fingerprint
        ):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Shared read-route control plane is not in the Phase U pinned local state"
            )
        integrity_proof_hash, _ = _fresh_source_and_candidate_proof(db, authorization=authorization)
        lease_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "authorization_id": str(authorization.id),
                "authorization_hash": authorization.authorization_hash,
                "authorization_request_snapshot_hash": authorization.request_snapshot_hash,
                "authorization_integrity_proof_hash": authorization.integrity_proof_hash,
                "authorization_approval_receipt_id": str(approval.id),
                "authorization_approval_receipt_hash": approval.receipt_hash,
                "phase_t_health_qualification_id": str(authorization.phase_t_health_qualification_id),
                "phase_t_health_qualification_hash": authorization.phase_t_health_qualification_hash,
                "operational_evidence_hash": authorization.operational_evidence_hash,
                "replica_id": str(authorization.replica_id),
                "replica_hash": authorization.replica_hash,
                "source_file_hash": authorization.source_file_hash,
                "source_file_size_bytes": authorization.source_file_size_bytes,
                "local_storage_key_fingerprint": authorization.local_storage_key_fingerprint,
                "recovery_bucket_fingerprint": authorization.recovery_bucket_fingerprint,
                "candidate_storage_key_fingerprint": authorization.candidate_storage_key_fingerprint,
                "source_authority_fingerprint": authorization.source_authority_fingerprint,
                "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
                "configuration_fingerprint": authorization.configuration_fingerprint,
                "verified_durable_read_count": authorization.verified_durable_read_count,
                "integrity_failure_count": authorization.integrity_failure_count,
                "storage_unavailable_count": authorization.storage_unavailable_count,
                "route_expired_attempt_count": authorization.route_expired_attempt_count,
                "operational_event_count": authorization.operational_event_count,
                "route_version_at_prepare": route.route_version,
                "integrity_proof_hash": integrity_proof_hash,
                "mode": "bounded_reversible_recovery_read_ownership_transition",
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return ReadOwnershipTransitionRoutingSnapshot(
            authorization_id=authorization.id,
            authorization_approval_receipt_id=approval.id,
            phase_t_health_qualification_id=authorization.phase_t_health_qualification_id,
            replica_id=authorization.replica_id,
            authorization_hash=authorization.authorization_hash,
            authorization_request_snapshot_hash=authorization.request_snapshot_hash,
            authorization_integrity_proof_hash=authorization.integrity_proof_hash,
            authorization_approval_receipt_hash=approval.receipt_hash,
            phase_t_health_qualification_hash=authorization.phase_t_health_qualification_hash,
            operational_evidence_hash=authorization.operational_evidence_hash,
            replica_hash=authorization.replica_hash,
            source_file_hash=authorization.source_file_hash,
            source_file_size_bytes=authorization.source_file_size_bytes,
            local_storage_key_fingerprint=authorization.local_storage_key_fingerprint,
            recovery_bucket_fingerprint=authorization.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=authorization.candidate_storage_key_fingerprint,
            source_authority_fingerprint=authorization.source_authority_fingerprint,
            candidate_authority_fingerprint=authorization.candidate_authority_fingerprint,
            configuration_fingerprint=authorization.configuration_fingerprint,
            verified_durable_read_count=authorization.verified_durable_read_count,
            integrity_failure_count=authorization.integrity_failure_count,
            storage_unavailable_count=authorization.storage_unavailable_count,
            route_expired_attempt_count=authorization.route_expired_attempt_count,
            operational_event_count=authorization.operational_event_count,
            route_version_at_prepare=route.route_version,
            integrity_proof_hash=integrity_proof_hash,
            lease_snapshot_hash=lease_snapshot_hash,
            authorization_approved_by_id=authorization.approved_by_id,
            authorization_expires_at=_as_utc(authorization.authorization_expires_at),
        )
    except RecoveryReadOwnershipTransitionRoutingError:
        raise
    except RecoveryReadOwnershipTransitionAuthorizationNotFound as exc:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(str(exc)) from exc
    except RecoveryReadOwnershipTransitionAuthorizationConflict as exc:
        raise RecoveryReadOwnershipTransitionRoutingConflict(str(exc)) from exc
    except RecoveryReadOwnershipTransitionAuthorizationUnavailable as exc:
        raise RecoveryReadOwnershipTransitionRoutingUnavailable(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryReadOwnershipTransitionRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryReadOwnershipTransitionRoutingUnavailable(str(exc)) from exc


def _matches_snapshot(
    lease: EvidenceRecoveryReadOwnershipTransitionLease,
    snapshot: ReadOwnershipTransitionRoutingSnapshot,
) -> bool:
    return all(
        getattr(lease, field) == getattr(snapshot, field)
        for field in ReadOwnershipTransitionRoutingSnapshot.__dataclass_fields__
        if field != "authorization_expires_at"
    )


def _get_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryReadOwnershipTransitionLease:
    stmt = select(EvidenceRecoveryReadOwnershipTransitionLease).where(
        EvidenceRecoveryReadOwnershipTransitionLease.id == lease_id,
        EvidenceRecoveryReadOwnershipTransitionLease.organization_id == organization_id,
        EvidenceRecoveryReadOwnershipTransitionLease.claim_id == claim_id,
        EvidenceRecoveryReadOwnershipTransitionLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(
            "Recovery read-ownership transition lease not found"
        )
    return lease


def _new_receipt(
    *,
    lease: EvidenceRecoveryReadOwnershipTransitionLease,
    phase: str,
    from_route_class: str,
    to_route_class: str,
    route_authority_kind: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryReadOwnershipTransitionReceipt:
    normalized_reason = reason.strip()
    switched = to_route_class == "recovery_replica" and route_authority_kind == "read_ownership_transition"
    receipt_hash = _canonical_hash(
        {
            "transition_lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "phase": phase,
            "from_route_class": from_route_class,
            "to_route_class": to_route_class,
            "route_authority_kind": route_authority_kind,
            "route_version": route_version,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "authorization_hash": lease.authorization_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": switched,
            "durable_read_route_created": switched,
            "read_ownership_authority_created": switched,
            "read_path_switched": switched,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryReadOwnershipTransitionReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        transition_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        phase=phase,
        from_route_class=from_route_class,
        to_route_class=to_route_class,
        route_authority_kind=route_authority_kind,
        route_version=route_version,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        lease_hash=lease.lease_hash,
        authorization_hash=lease.authorization_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=switched,
        durable_read_route_created=switched,
        read_ownership_authority_created=switched,
        read_path_switched=switched,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )


def _terminalize_prepared(
    db: Session,
    *,
    lease: EvidenceRecoveryReadOwnershipTransitionLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryReadOwnershipTransitionReceipt:
    if not _route_is_clean_local(route):
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Prepared Phase V lease cannot terminalize while another read authority is active"
        )
    lease.status = status
    lease.terminal_by_id = actor_id
    lease.terminal_at = now
    lease.terminal_reason = reason
    receipt = _new_receipt(
        lease=lease,
        phase=status,
        from_route_class="local_source",
        to_route_class="local_source",
        route_authority_kind="local",
        route_version=route.route_version,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def prepare_recovery_read_ownership_transition_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryReadOwnershipTransitionLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryReadOwnershipTransitionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Phase V preparation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    existing = db.scalar(
        select(EvidenceRecoveryReadOwnershipTransitionLease)
        .where(
            EvidenceRecoveryReadOwnershipTransitionLease.organization_id == organization_id,
            EvidenceRecoveryReadOwnershipTransitionLease.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.prepared_by_id != prepared_by_id or existing.preparation_reason != normalized_reason:
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V preparation replay must use the original preparer and reason"
            )
        if existing.status in {"prepared", "activated", "rolled_back"}:
            return existing, route, None, "unchanged"
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "A terminal Phase V lease already exists for this Phase U authorization"
        )
    snapshot = _load_preparation_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        now=current_time,
    )
    if not _route_is_clean_local(route) or route.route_version != snapshot.route_version_at_prepare:
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Read route drifted before Phase V lease creation"
        )
    lease_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "authorization_id": str(authorization_id),
            "authorization_hash": snapshot.authorization_hash,
            "lease_snapshot_hash": snapshot.lease_snapshot_hash,
            "prepared_by_id": str(prepared_by_id),
            "prepared_at": _utc_iso(current_time),
            "activation_expires_at": _utc_iso(snapshot.authorization_expires_at),
            "max_route_window_seconds": int(READ_OWNERSHIP_TRANSITION_ROUTE_WINDOW.total_seconds()),
            "mode": "phase_v_bounded_reversible_read_ownership_transition",
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    lease = EvidenceRecoveryReadOwnershipTransitionLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=snapshot.authorization_id,
        authorization_approval_receipt_id=snapshot.authorization_approval_receipt_id,
        phase_t_health_qualification_id=snapshot.phase_t_health_qualification_id,
        replica_id=snapshot.replica_id,
        authorization_hash=snapshot.authorization_hash,
        authorization_request_snapshot_hash=snapshot.authorization_request_snapshot_hash,
        authorization_integrity_proof_hash=snapshot.authorization_integrity_proof_hash,
        authorization_approval_receipt_hash=snapshot.authorization_approval_receipt_hash,
        phase_t_health_qualification_hash=snapshot.phase_t_health_qualification_hash,
        operational_evidence_hash=snapshot.operational_evidence_hash,
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
        route_expired_attempt_count=snapshot.route_expired_attempt_count,
        operational_event_count=snapshot.operational_event_count,
        route_version_at_prepare=snapshot.route_version_at_prepare,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        lease_snapshot_hash=snapshot.lease_snapshot_hash,
        lease_hash=lease_hash,
        status="prepared",
        activation_expires_at=snapshot.authorization_expires_at,
        route_expires_at=None,
        authorization_approved_by_id=snapshot.authorization_approved_by_id,
        prepared_by_id=prepared_by_id,
        prepared_at=current_time,
        preparation_reason=normalized_reason,
        routable_authority_created=False,
        durable_read_route_created=False,
        read_ownership_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(lease)
    db.flush()
    receipt = _new_receipt(
        lease=lease,
        phase="prepared",
        from_route_class="local_source",
        to_route_class="local_source",
        route_authority_kind="local",
        route_version=route.route_version,
        actor_id=prepared_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, route, receipt, "prepared"


def activate_recovery_read_ownership_transition_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryReadOwnershipTransitionLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryReadOwnershipTransitionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionRoutingConflict("Phase V activation reason is required")
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, lease_id=lease_id, for_update=True)
    route = _get_route(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, for_update=True)
    assert route is not None
    if lease.status == "activated":
        if not all(
            (
                lease.activated_by_id == activated_by_id,
                lease.activation_reason == normalized_reason,
                route.route_class == "recovery_replica",
                route.route_authority_kind == "read_ownership_transition",
                route.active_read_ownership_transition_lease_id == lease.id,
                route.active_replica_id == lease.replica_id,
                route.read_path_switched is True,
            )
        ):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V activation replay does not match active authority"
            )
        return lease, route, None, "unchanged"
    if lease.status != "prepared":
        raise RecoveryReadOwnershipTransitionRoutingConflict("Only a prepared Phase V lease can be activated")
    if lease.prepared_by_id == activated_by_id:
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Phase V activation requires a different Admin from the preparer"
        )
    if lease.authorization_approved_by_id == activated_by_id:
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Phase V activator must differ from the Phase U approver"
        )
    if current_time >= _as_utc(lease.activation_expires_at):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=activated_by_id,
            reason="Phase V activation window expired",
            now=current_time,
        )
        return lease, route, receipt, "expired"
    try:
        snapshot = _load_preparation_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=lease.authorization_id,
            now=current_time,
        )
    except RecoveryReadOwnershipTransitionRoutingUnavailable:
        raise
    except (RecoveryReadOwnershipTransitionRoutingConflict, RecoveryReadOwnershipTransitionRoutingNotFound) as exc:
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh Phase V preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"
    if not _matches_snapshot(lease, snapshot) or not _route_is_clean_local(route):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason="Phase V lineage or route drifted before activation",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"

    lease.status = "activated"
    lease.activated_by_id = activated_by_id
    lease.activated_at = current_time
    lease.activation_reason = normalized_reason
    lease.route_expires_at = current_time + READ_OWNERSHIP_TRANSITION_ROUTE_WINDOW
    lease.routable_authority_created = True
    lease.durable_read_route_created = True
    lease.read_ownership_authority_created = True
    lease.read_path_switched = True

    route.route_class = "recovery_replica"
    route.route_authority_kind = "read_ownership_transition"
    route.active_lease_id = None
    route.active_durable_lease_id = None
    route.active_durable_renewal_lease_id = None
    route.active_durable_reauthorized_renewal_lease_id = None
    route.active_read_ownership_transition_lease_id = lease.id
    route.active_replica_id = lease.replica_id
    route.route_version += 1
    route.changed_by_id = activated_by_id
    route.changed_at = current_time
    route.read_path_switched = True

    receipt = _new_receipt(
        lease=lease,
        phase="activated",
        from_route_class="local_source",
        to_route_class="recovery_replica",
        route_authority_kind="read_ownership_transition",
        route_version=route.route_version,
        actor_id=activated_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, route, receipt, "activated"


def _restore_local_route(
    db: Session,
    *,
    lease: EvidenceRecoveryReadOwnershipTransitionLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryReadOwnershipTransitionReceipt:
    if not all(
        (
            route.route_class == "recovery_replica",
            route.route_authority_kind == "read_ownership_transition",
            route.active_lease_id is None,
            route.active_durable_lease_id is None,
            route.active_durable_renewal_lease_id is None,
            route.active_durable_reauthorized_renewal_lease_id is None,
            route.active_read_ownership_transition_lease_id == lease.id,
            route.active_replica_id == lease.replica_id,
            route.read_path_switched is True,
        )
    ):
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Active read route does not match the Phase V lease being restored"
        )
    route.route_class = "local_source"
    route.route_authority_kind = "local"
    route.active_lease_id = None
    route.active_durable_lease_id = None
    route.active_durable_renewal_lease_id = None
    route.active_durable_reauthorized_renewal_lease_id = None
    route.active_read_ownership_transition_lease_id = None
    route.active_replica_id = None
    route.route_version += 1
    route.changed_by_id = actor_id
    route.changed_at = now
    route.read_path_switched = False

    lease.status = status
    lease.routable_authority_created = False
    lease.durable_read_route_created = False
    lease.read_ownership_authority_created = False
    lease.read_path_switched = False
    if status == "rolled_back":
        lease.rolled_back_by_id = actor_id
        lease.rolled_back_at = now
        lease.rollback_reason = reason
    else:
        lease.terminal_by_id = actor_id
        lease.terminal_at = now
        lease.terminal_reason = reason
    receipt = _new_receipt(
        lease=lease,
        phase=status,
        from_route_class="recovery_replica",
        to_route_class="local_source",
        route_authority_kind="local",
        route_version=route.route_version,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def rollback_recovery_read_ownership_transition_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryReadOwnershipTransitionLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryReadOwnershipTransitionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionRoutingConflict("Phase V rollback reason is required")
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, lease_id=lease_id, for_update=True)
    route = _get_route(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, for_update=True)
    assert route is not None
    if lease.status == "rolled_back":
        if not (lease.rolled_back_by_id == rolled_back_by_id and lease.rollback_reason == normalized_reason and _route_is_clean_local(route)):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V rollback replay does not match the original rollback"
            )
        return lease, route, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryReadOwnershipTransitionRoutingConflict("Only an activated Phase V lease can be rolled back")
    receipt = _restore_local_route(
        db,
        lease=lease,
        route=route,
        status="rolled_back",
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        now=current_time,
    )
    return lease, route, receipt, "rolled_back"


def reconcile_recovery_read_ownership_transition_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    reconciled_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryReadOwnershipTransitionLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryReadOwnershipTransitionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadOwnershipTransitionRoutingConflict("Phase V reconciliation reason is required")
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, lease_id=lease_id, for_update=True)
    route = _get_route(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, for_update=True)
    assert route is not None
    if lease.status in {"rolled_back", "expired"} and _route_is_clean_local(route):
        return lease, route, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryReadOwnershipTransitionRoutingConflict("Only an activated Phase V lease can be reconciled")
    if lease.route_expires_at is None or current_time < _as_utc(lease.route_expires_at):
        return lease, route, None, "unchanged"
    receipt = _restore_local_route(
        db,
        lease=lease,
        route=route,
        status="expired",
        actor_id=reconciled_by_id,
        reason=normalized_reason,
        now=current_time,
    )
    return lease, route, receipt, "expired"


def _active_lease_and_payload(
    db: Session,
    *,
    document: Document,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryReadOwnershipTransitionLease, bytes]:
    current_time = _as_utc(now or _utc_now())
    route = _get_route(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
    )
    if route is None or route.route_authority_kind != "read_ownership_transition" or route.active_read_ownership_transition_lease_id is None:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(
            "No active Phase V read-ownership transition route exists"
        )
    lease = _get_lease(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        lease_id=route.active_read_ownership_transition_lease_id,
    )
    if lease.status != "activated" or lease.route_expires_at is None:
        raise RecoveryReadOwnershipTransitionRoutingConflict("Phase V read authority is not active")
    if current_time >= _as_utc(lease.route_expires_at):
        raise RecoveryReadOwnershipTransitionRoutingConflict("Phase V read-ownership route expired")
    if not all(
        (
            route.route_class == "recovery_replica",
            route.route_authority_kind == "read_ownership_transition",
            route.active_lease_id is None,
            route.active_durable_lease_id is None,
            route.active_durable_renewal_lease_id is None,
            route.active_durable_reauthorized_renewal_lease_id is None,
            route.active_read_ownership_transition_lease_id == lease.id,
            route.active_replica_id == lease.replica_id,
            route.route_version == lease.route_version_at_prepare + 1,
            route.source_authority_fingerprint == lease.source_authority_fingerprint,
            route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            route.configuration_fingerprint == lease.configuration_fingerprint,
            route.read_path_switched is True,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
        )
    ):
        raise RecoveryReadOwnershipTransitionRoutingConflict(
            "Phase V shared read-route binding drifted"
        )
    try:
        authorization = _get_authorization(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            authorization_id=lease.authorization_id,
        )
        if authorization.status != "approved" or authorization.authorization_hash != lease.authorization_hash:
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U authorization no longer matches active Phase V authority"
            )
        authorization_snapshot = _load_authorization_snapshot(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            phase_t_health_qualification_id=authorization.phase_t_health_qualification_id,
        )
        if not _matches_authorization_snapshot(authorization, authorization_snapshot):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U lineage drifted while Phase V owned reads"
            )
        approval = _approval_receipt(db, authorization=authorization)
        if approval.id != lease.authorization_approval_receipt_id or approval.receipt_hash != lease.authorization_approval_receipt_hash:
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U approval receipt drifted while Phase V owned reads"
            )
        integrity_proof_hash, payload = _fresh_source_and_candidate_proof(db, authorization=authorization)
        if integrity_proof_hash != lease.integrity_proof_hash:
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V fresh integrity proof no longer matches the prepared lease"
            )
        return lease, payload
    except RecoveryReadOwnershipTransitionRoutingError:
        raise
    except RecoveryReadOwnershipTransitionAuthorizationNotFound as exc:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(str(exc)) from exc
    except RecoveryReadOwnershipTransitionAuthorizationConflict as exc:
        raise RecoveryReadOwnershipTransitionRoutingConflict(str(exc)) from exc
    except RecoveryReadOwnershipTransitionAuthorizationUnavailable as exc:
        raise RecoveryReadOwnershipTransitionRoutingUnavailable(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryReadOwnershipTransitionRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryReadOwnershipTransitionRoutingUnavailable(str(exc)) from exc


def resolve_recovery_document_read_ownership_transition(
    db: Session,
    *,
    document: Document,
    now: datetime | None = None,
) -> tuple[bytes, str]:
    _, payload = _active_lease_and_payload(db, document=document, now=now)
    return payload, "recovery-replica-read-ownership-transition"


def get_recovery_read_ownership_transition_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryReadOwnershipTransitionLease:
    return _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )


def list_recovery_read_ownership_transition_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> list[EvidenceRecoveryReadOwnershipTransitionReceipt]:
    _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryReadOwnershipTransitionReceipt)
            .where(
                EvidenceRecoveryReadOwnershipTransitionReceipt.organization_id == organization_id,
                EvidenceRecoveryReadOwnershipTransitionReceipt.claim_id == claim_id,
                EvidenceRecoveryReadOwnershipTransitionReceipt.document_id == document_id,
                EvidenceRecoveryReadOwnershipTransitionReceipt.transition_lease_id == lease_id,
            )
            .order_by(EvidenceRecoveryReadOwnershipTransitionReceipt.transitioned_at.asc())
        ).all()
    )
