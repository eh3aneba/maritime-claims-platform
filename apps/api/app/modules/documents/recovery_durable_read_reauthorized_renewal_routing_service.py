from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_renewal_health_models import (
    EvidenceRecoveryDurableReadRenewalHealthQualification,
    EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_reauthorization_models import (
    EvidenceRecoveryDurableReadRenewalReauthorization,
    EvidenceRecoveryDurableReadRenewalReauthorizationReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_reauthorization_service import (
    RecoveryDurableReadRenewalReauthorizationConflict,
    RecoveryDurableReadRenewalReauthorizationNotFound,
    RecoveryDurableReadRenewalReauthorizationUnavailable,
    _get_authorization as _get_reauthorization,
    _load_snapshot as _load_reauthorization_snapshot,
    _matches_snapshot as _matches_reauthorization_snapshot,
)
from app.modules.documents.recovery_durable_read_renewal_routing_models import (
    EvidenceRecoveryDurableReadRenewalLease,
)
from app.modules.documents.recovery_durable_read_renewal_routing_service import (
    RecoveryDurableReadRenewalRoutingConflict,
    RecoveryDurableReadRenewalRoutingNotFound,
    RecoveryDurableReadRenewalRoutingUnavailable,
    _get_lease as _get_prior_renewal_lease,
)
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    EvidenceRecoveryDurableReadReauthorizedRenewalReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
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

DURABLE_READ_REAUTHORIZED_RENEWAL_ROUTE_WINDOW = timedelta(hours=24)


class RecoveryDurableReadReauthorizedRenewalRoutingError(RuntimeError):
    pass


class RecoveryDurableReadReauthorizedRenewalRoutingNotFound(
    RecoveryDurableReadReauthorizedRenewalRoutingError
):
    pass


class RecoveryDurableReadReauthorizedRenewalRoutingConflict(
    RecoveryDurableReadReauthorizedRenewalRoutingError
):
    pass


class RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(
    RecoveryDurableReadReauthorizedRenewalRoutingError
):
    pass


@dataclass(frozen=True)
class DurableReadReauthorizedRenewalRoutingSnapshot:
    reauthorization_id: UUID
    reauthorization_approval_receipt_id: UUID
    phase_q_health_qualification_id: UUID
    prior_renewal_lease_id: UUID
    replica_id: UUID
    reauthorization_hash: str
    reauthorization_request_snapshot_hash: str
    reauthorization_integrity_proof_hash: str
    reauthorization_approval_receipt_hash: str
    phase_q_health_qualification_hash: str
    operational_evidence_hash: str
    prior_renewal_lease_hash: str
    prior_lease_snapshot_hash: str
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
    route_version_at_prepare: int
    integrity_proof_hash: str
    lease_snapshot_hash: str
    reauthorization_approved_by_id: UUID
    phase_q_qualified_by_id: UUID
    prior_renewal_activated_by_id: UUID
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
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
) -> EvidenceRecoveryDurableReadRenewalReauthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalReauthorizationReceipt).where(
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.organization_id
                == authorization.organization_id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.claim_id
                == authorization.claim_id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.document_id
                == authorization.document_id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.reauthorization_id
                == authorization.id,
                EvidenceRecoveryDurableReadRenewalReauthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Approved Phase R authorization must have exactly one approval receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.phase_q_health_qualification_id
            == authorization.phase_q_health_qualification_id,
            receipt.renewal_lease_id == authorization.renewal_lease_id,
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
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase R approval receipt lineage is inconsistent"
        )
    return receipt


def _qualified_q_receipt(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableReadRenewalHealthQualification,
) -> EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt).where(
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.organization_id
                == qualification.organization_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.claim_id
                == qualification.claim_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.document_id
                == qualification.document_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.health_qualification_id
                == qualification.id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase Q qualification must retain exactly one qualified receipt"
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
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase Q qualified receipt lineage is inconsistent"
        )
    return receipt


def _prior_renewal_matches_reauthorization(
    lease: EvidenceRecoveryDurableReadRenewalLease,
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
) -> bool:
    return all(
        (
            lease.id == authorization.renewal_lease_id,
            lease.status in {"rolled_back", "expired"},
            lease.activated_by_id == authorization.renewal_activated_by_id,
            lease.lease_hash == authorization.renewal_lease_hash,
            lease.lease_snapshot_hash == authorization.lease_snapshot_hash,
            lease.replica_id == authorization.replica_id,
            lease.replica_hash == authorization.replica_hash,
            lease.source_file_hash == authorization.source_file_hash,
            lease.source_file_size_bytes == authorization.source_file_size_bytes,
            lease.local_storage_key_fingerprint == authorization.local_storage_key_fingerprint,
            lease.recovery_bucket_fingerprint == authorization.recovery_bucket_fingerprint,
            lease.candidate_storage_key_fingerprint
            == authorization.candidate_storage_key_fingerprint,
            lease.source_authority_fingerprint == authorization.source_authority_fingerprint,
            lease.candidate_authority_fingerprint == authorization.candidate_authority_fingerprint,
            lease.configuration_fingerprint == authorization.configuration_fingerprint,
            lease.routable_authority_created is False,
            lease.durable_read_route_created is False,
            lease.read_path_switched is False,
            lease.write_path_switched is False,
            lease.document_storage_key_mutated is False,
            lease.authoritative_storage_changed is False,
            lease.destructive_action_performed is False,
            lease.s3_delete_performed is False,
            lease.local_delete_performed is False,
        )
    )


def _fresh_source_and_candidate_proof(
    db: Session,
    *,
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
) -> str:
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
            local_snapshot.storage_key_fingerprint
            == authorization.local_storage_key_fingerprint,
            replica.replica_hash == authorization.replica_hash,
            replica.recovery_bucket_fingerprint
            == authorization.recovery_bucket_fingerprint,
            hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
            == authorization.candidate_storage_key_fingerprint,
            hashlib.sha256(candidate_payload).hexdigest() == authorization.source_file_hash,
            len(candidate_payload) == authorization.source_file_size_bytes,
        )
    ):
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Fresh local or recovery candidate integrity does not match Phase R"
        )
    return _canonical_hash(
        {
            "reauthorization_id": str(authorization.id),
            "phase_q_health_qualification_id": str(authorization.phase_q_health_qualification_id),
            "prior_renewal_lease_id": str(authorization.renewal_lease_id),
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


def _load_preparation_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    reauthorization_id: UUID,
    now: datetime | None = None,
) -> DurableReadReauthorizedRenewalRoutingSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        authorization = _get_reauthorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=reauthorization_id,
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
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Only an approved healthy Phase R authorization can prepare routing"
            )
        if current_time >= _as_utc(authorization.authorization_expires_at):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Approved Phase R authorization is outside its consumption window"
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
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase R authorization crossed its non-routable safety boundary"
            )
        reauthorization_snapshot = _load_reauthorization_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_q_health_qualification_id=authorization.phase_q_health_qualification_id,
        )
        if not _matches_reauthorization_snapshot(authorization, reauthorization_snapshot):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase R authorization lineage drifted before routing preparation"
            )
        approval = _approval_receipt(db, authorization=authorization)
        prior_renewal = _get_prior_renewal_lease(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=authorization.renewal_lease_id,
        )
        if not _prior_renewal_matches_reauthorization(prior_renewal, authorization):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Prior Phase P renewal lease no longer matches Phase R"
            )
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
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Single read-route control plane is not in the Phase R pinned local state"
            )
        integrity_proof_hash = _fresh_source_and_candidate_proof(db, authorization=authorization)
        lease_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "reauthorization_id": str(authorization.id),
                "reauthorization_hash": authorization.authorization_hash,
                "reauthorization_request_snapshot_hash": authorization.request_snapshot_hash,
                "reauthorization_integrity_proof_hash": authorization.integrity_proof_hash,
                "reauthorization_approval_receipt_id": str(approval.id),
                "reauthorization_approval_receipt_hash": approval.receipt_hash,
                "phase_q_health_qualification_id": str(authorization.phase_q_health_qualification_id),
                "phase_q_health_qualification_hash": authorization.phase_q_health_qualification_hash,
                "operational_evidence_hash": authorization.operational_evidence_hash,
                "prior_renewal_lease_id": str(authorization.renewal_lease_id),
                "prior_renewal_lease_hash": authorization.renewal_lease_hash,
                "prior_lease_snapshot_hash": authorization.lease_snapshot_hash,
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
                "route_version_at_prepare": route.route_version,
                "integrity_proof_hash": integrity_proof_hash,
                "mode": "bounded_reversible_reauthorized_durable_read_renewal",
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return DurableReadReauthorizedRenewalRoutingSnapshot(
            reauthorization_id=authorization.id,
            reauthorization_approval_receipt_id=approval.id,
            phase_q_health_qualification_id=authorization.phase_q_health_qualification_id,
            prior_renewal_lease_id=authorization.renewal_lease_id,
            replica_id=authorization.replica_id,
            reauthorization_hash=authorization.authorization_hash,
            reauthorization_request_snapshot_hash=authorization.request_snapshot_hash,
            reauthorization_integrity_proof_hash=authorization.integrity_proof_hash,
            reauthorization_approval_receipt_hash=approval.receipt_hash,
            phase_q_health_qualification_hash=authorization.phase_q_health_qualification_hash,
            operational_evidence_hash=authorization.operational_evidence_hash,
            prior_renewal_lease_hash=authorization.renewal_lease_hash,
            prior_lease_snapshot_hash=authorization.lease_snapshot_hash,
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
            route_version_at_prepare=route.route_version,
            integrity_proof_hash=integrity_proof_hash,
            lease_snapshot_hash=lease_snapshot_hash,
            reauthorization_approved_by_id=authorization.approved_by_id,
            phase_q_qualified_by_id=authorization.phase_q_qualified_by_id,
            prior_renewal_activated_by_id=authorization.renewal_activated_by_id,
            authorization_expires_at=_as_utc(authorization.authorization_expires_at),
        )
    except RecoveryDurableReadReauthorizedRenewalRoutingError:
        raise
    except RecoveryDurableReadRenewalReauthorizationNotFound as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalReauthorizationConflict as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalReauthorizationUnavailable as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(str(exc)) from exc
    except RecoveryDurableReadRenewalRoutingNotFound as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalRoutingConflict as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalRoutingUnavailable as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(str(exc)) from exc


def _matches_snapshot(
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    snapshot: DurableReadReauthorizedRenewalRoutingSnapshot,
) -> bool:
    return all(
        (
            lease.reauthorization_id == snapshot.reauthorization_id,
            lease.reauthorization_approval_receipt_id == snapshot.reauthorization_approval_receipt_id,
            lease.phase_q_health_qualification_id == snapshot.phase_q_health_qualification_id,
            lease.prior_renewal_lease_id == snapshot.prior_renewal_lease_id,
            lease.replica_id == snapshot.replica_id,
            lease.reauthorization_hash == snapshot.reauthorization_hash,
            lease.reauthorization_request_snapshot_hash == snapshot.reauthorization_request_snapshot_hash,
            lease.reauthorization_integrity_proof_hash == snapshot.reauthorization_integrity_proof_hash,
            lease.reauthorization_approval_receipt_hash == snapshot.reauthorization_approval_receipt_hash,
            lease.phase_q_health_qualification_hash == snapshot.phase_q_health_qualification_hash,
            lease.operational_evidence_hash == snapshot.operational_evidence_hash,
            lease.prior_renewal_lease_hash == snapshot.prior_renewal_lease_hash,
            lease.prior_lease_snapshot_hash == snapshot.prior_lease_snapshot_hash,
            lease.replica_hash == snapshot.replica_hash,
            lease.source_file_hash == snapshot.source_file_hash,
            lease.source_file_size_bytes == snapshot.source_file_size_bytes,
            lease.local_storage_key_fingerprint == snapshot.local_storage_key_fingerprint,
            lease.recovery_bucket_fingerprint == snapshot.recovery_bucket_fingerprint,
            lease.candidate_storage_key_fingerprint == snapshot.candidate_storage_key_fingerprint,
            lease.source_authority_fingerprint == snapshot.source_authority_fingerprint,
            lease.candidate_authority_fingerprint == snapshot.candidate_authority_fingerprint,
            lease.configuration_fingerprint == snapshot.configuration_fingerprint,
            lease.verified_durable_read_count == snapshot.verified_durable_read_count,
            lease.integrity_failure_count == snapshot.integrity_failure_count,
            lease.storage_unavailable_count == snapshot.storage_unavailable_count,
            lease.route_version_at_prepare == snapshot.route_version_at_prepare,
            lease.integrity_proof_hash == snapshot.integrity_proof_hash,
            lease.lease_snapshot_hash == snapshot.lease_snapshot_hash,
            lease.reauthorization_approved_by_id == snapshot.reauthorization_approved_by_id,
            lease.phase_q_qualified_by_id == snapshot.phase_q_qualified_by_id,
            lease.prior_renewal_activated_by_id == snapshot.prior_renewal_activated_by_id,
        )
    )


def _get_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalLease:
    stmt = select(EvidenceRecoveryDurableReadReauthorizedRenewalLease).where(
        EvidenceRecoveryDurableReadReauthorizedRenewalLease.id == lease_id,
        EvidenceRecoveryDurableReadReauthorizedRenewalLease.organization_id == organization_id,
        EvidenceRecoveryDurableReadReauthorizedRenewalLease.claim_id == claim_id,
        EvidenceRecoveryDurableReadReauthorizedRenewalLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(
            "Recovery durable reauthorized renewal lease not found"
        )
    return lease


def _new_receipt(
    *,
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    phase: str,
    from_route_class: str,
    to_route_class: str,
    route_authority_kind: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalReceipt:
    normalized_reason = reason.strip()
    switched = to_route_class == "recovery_replica" and route_authority_kind == "durable_reauthorized_renewal"
    receipt_hash = _canonical_hash(
        {
            "reauthorized_renewal_lease_id": str(lease.id),
            "reauthorization_id": str(lease.reauthorization_id),
            "phase": phase,
            "from_route_class": from_route_class,
            "to_route_class": to_route_class,
            "route_authority_kind": route_authority_kind,
            "route_version": route_version,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "reauthorization_hash": lease.reauthorization_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": switched,
            "durable_read_route_created": switched,
            "read_path_switched": switched,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryDurableReadReauthorizedRenewalReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        reauthorized_renewal_lease_id=lease.id,
        reauthorization_id=lease.reauthorization_id,
        phase=phase,
        from_route_class=from_route_class,
        to_route_class=to_route_class,
        route_authority_kind=route_authority_kind,
        route_version=route_version,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        lease_hash=lease.lease_hash,
        reauthorization_hash=lease.reauthorization_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=switched,
        durable_read_route_created=switched,
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
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalReceipt:
    lease.status = status
    lease.terminal_by_id = actor_id
    lease.terminal_at = now
    lease.terminal_reason = reason
    lease.routable_authority_created = False
    lease.durable_read_route_created = False
    lease.read_path_switched = False
    receipt = _new_receipt(
        lease=lease,
        phase=status,
        from_route_class=route.route_class,
        to_route_class=route.route_class,
        route_authority_kind=route.route_authority_kind,
        route_version=route.route_version,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def prepare_recovery_durable_read_reauthorized_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    reauthorization_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadReauthorizedRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadReauthorizedRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Reauthorized renewal lease preparation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_preparation_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        reauthorization_id=reauthorization_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadReauthorizedRenewalLease)
        .where(
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.organization_id == organization_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.claim_id == claim_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.document_id == document_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.reauthorization_id == reauthorization_id,
        )
        .with_for_update()
    )
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    if existing is not None:
        if not (existing.prepared_by_id == prepared_by_id and existing.preparation_reason == normalized_reason):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Reauthorized renewal lease exists with different preparation semantics"
            )
        if _matches_snapshot(existing, snapshot):
            if existing.status == "prepared" and _route_is_clean_local(route):
                return existing, route, None, "unchanged"
            if existing.status == "activated" and all(
                (
                    route.route_class == "recovery_replica",
                    route.route_authority_kind == "durable_reauthorized_renewal",
                    route.active_lease_id is None,
                    route.active_durable_lease_id is None,
                    route.active_durable_renewal_lease_id is None,
                    route.active_durable_reauthorized_renewal_lease_id == existing.id,
                    route.active_replica_id == existing.replica_id,
                )
            ):
                return existing, route, None, "unchanged"
            if existing.status == "rolled_back" and _route_is_clean_local(route):
                return existing, route, None, "unchanged"
        if existing.status == "prepared":
            receipt = _terminalize_prepared(
                db,
                lease=existing,
                route=route,
                status="invalidated",
                actor_id=prepared_by_id,
                reason="Phase S lineage drifted before preparation replay",
                now=current_time,
            )
            return existing, route, receipt, "invalidated"
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "A terminal Phase S lease already exists for this reauthorization"
        )
    if not _route_is_clean_local(route):
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Another temporary or durable read authority is already active"
        )
    if route.route_version != snapshot.route_version_at_prepare:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Read route version drifted before Phase S lease creation"
        )
    lease_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "reauthorization_id": str(reauthorization_id),
            "reauthorization_hash": snapshot.reauthorization_hash,
            "lease_snapshot_hash": snapshot.lease_snapshot_hash,
            "prepared_by_id": str(prepared_by_id),
            "prepared_at": _utc_iso(current_time),
            "activation_expires_at": _utc_iso(snapshot.authorization_expires_at),
            "max_route_window_seconds": int(DURABLE_READ_REAUTHORIZED_RENEWAL_ROUTE_WINDOW.total_seconds()),
            "mode": "bounded_reversible_reauthorized_durable_read_renewal_lease",
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    lease = EvidenceRecoveryDurableReadReauthorizedRenewalLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        reauthorization_id=snapshot.reauthorization_id,
        reauthorization_approval_receipt_id=snapshot.reauthorization_approval_receipt_id,
        phase_q_health_qualification_id=snapshot.phase_q_health_qualification_id,
        prior_renewal_lease_id=snapshot.prior_renewal_lease_id,
        replica_id=snapshot.replica_id,
        reauthorization_hash=snapshot.reauthorization_hash,
        reauthorization_request_snapshot_hash=snapshot.reauthorization_request_snapshot_hash,
        reauthorization_integrity_proof_hash=snapshot.reauthorization_integrity_proof_hash,
        reauthorization_approval_receipt_hash=snapshot.reauthorization_approval_receipt_hash,
        phase_q_health_qualification_hash=snapshot.phase_q_health_qualification_hash,
        operational_evidence_hash=snapshot.operational_evidence_hash,
        prior_renewal_lease_hash=snapshot.prior_renewal_lease_hash,
        prior_lease_snapshot_hash=snapshot.prior_lease_snapshot_hash,
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
        route_version_at_prepare=snapshot.route_version_at_prepare,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        lease_snapshot_hash=snapshot.lease_snapshot_hash,
        lease_hash=lease_hash,
        status="prepared",
        activation_expires_at=snapshot.authorization_expires_at,
        route_expires_at=None,
        reauthorization_approved_by_id=snapshot.reauthorization_approved_by_id,
        phase_q_qualified_by_id=snapshot.phase_q_qualified_by_id,
        prior_renewal_activated_by_id=snapshot.prior_renewal_activated_by_id,
        prepared_by_id=prepared_by_id,
        prepared_at=current_time,
        preparation_reason=normalized_reason,
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


def activate_recovery_durable_read_reauthorized_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadReauthorizedRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadReauthorizedRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Reauthorized renewal activation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    if lease.status == "activated":
        if not all(
            (
                lease.activated_by_id == activated_by_id,
                lease.activation_reason == normalized_reason,
                route.route_class == "recovery_replica",
                route.route_authority_kind == "durable_reauthorized_renewal",
                route.active_lease_id is None,
                route.active_durable_lease_id is None,
                route.active_durable_renewal_lease_id is None,
                route.active_durable_reauthorized_renewal_lease_id == lease.id,
                route.active_replica_id == lease.replica_id,
                route.read_path_switched is True,
            )
        ):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase S activation replay does not match active authority"
            )
        return lease, route, None, "unchanged"
    if lease.status != "prepared":
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Only a prepared Phase S lease can be activated"
        )
    if lease.prepared_by_id == activated_by_id:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase S activation requires a different Admin from the preparer"
        )
    if lease.reauthorization_approved_by_id == activated_by_id:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase S activator must differ from the Phase R approver"
        )
    if lease.phase_q_qualified_by_id == activated_by_id:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase S activator must differ from the Phase Q qualifier"
        )
    if lease.prior_renewal_activated_by_id == activated_by_id:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase S activator must differ from the prior Phase P activator"
        )
    if current_time >= _as_utc(lease.activation_expires_at):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=activated_by_id,
            reason="Phase S activation window expired",
            now=current_time,
        )
        return lease, route, receipt, "expired"
    try:
        snapshot = _load_preparation_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            reauthorization_id=lease.reauthorization_id,
            now=current_time,
        )
    except RecoveryDurableReadReauthorizedRenewalRoutingUnavailable:
        raise
    except (RecoveryDurableReadReauthorizedRenewalRoutingConflict, RecoveryDurableReadReauthorizedRenewalRoutingNotFound) as exc:
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh Phase S preflight failed: {type(exc).__name__}",
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
            reason="Phase S lineage or route drifted before activation",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"
    lease.status = "activated"
    lease.activated_by_id = activated_by_id
    lease.activated_at = current_time
    lease.activation_reason = normalized_reason
    lease.route_expires_at = current_time + DURABLE_READ_REAUTHORIZED_RENEWAL_ROUTE_WINDOW
    lease.routable_authority_created = True
    lease.durable_read_route_created = True
    lease.read_path_switched = True

    route.route_class = "recovery_replica"
    route.route_authority_kind = "durable_reauthorized_renewal"
    route.active_lease_id = None
    route.active_durable_lease_id = None
    route.active_durable_renewal_lease_id = None
    route.active_durable_reauthorized_renewal_lease_id = lease.id
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
        route_authority_kind="durable_reauthorized_renewal",
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
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalReceipt:
    if not all(
        (
            route.route_class == "recovery_replica",
            route.route_authority_kind == "durable_reauthorized_renewal",
            route.active_lease_id is None,
            route.active_durable_lease_id is None,
            route.active_durable_renewal_lease_id is None,
            route.active_durable_reauthorized_renewal_lease_id == lease.id,
            route.active_replica_id == lease.replica_id,
            route.read_path_switched is True,
        )
    ):
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Active read route does not match the Phase S lease being restored"
        )
    route.route_class = "local_source"
    route.route_authority_kind = "local"
    route.active_lease_id = None
    route.active_durable_lease_id = None
    route.active_durable_renewal_lease_id = None
    route.active_durable_reauthorized_renewal_lease_id = None
    route.active_replica_id = None
    route.route_version += 1
    route.changed_by_id = actor_id
    route.changed_at = now
    route.read_path_switched = False

    lease.status = status
    lease.routable_authority_created = False
    lease.durable_read_route_created = False
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


def rollback_recovery_durable_read_reauthorized_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadReauthorizedRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadReauthorizedRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict("Phase S rollback reason is required")
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    if lease.status == "rolled_back":
        if not (lease.rolled_back_by_id == rolled_back_by_id and lease.rollback_reason == normalized_reason and _route_is_clean_local(route)):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase S rollback replay does not match the original rollback"
            )
        return lease, route, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Only an activated Phase S lease can be rolled back"
        )
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


def _active_q_lineage_matches(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    authorization: EvidenceRecoveryDurableReadRenewalReauthorization,
) -> bool:
    qualification = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalHealthQualification).where(
            EvidenceRecoveryDurableReadRenewalHealthQualification.id == lease.phase_q_health_qualification_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.organization_id == lease.organization_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.document_id == lease.document_id,
        )
    )
    if qualification is None:
        return False
    if not all(
        (
            qualification.status == "qualified",
            qualification.health_state == "healthy",
            qualification.qualified_by_id == lease.phase_q_qualified_by_id,
            qualification.health_qualification_hash == lease.phase_q_health_qualification_hash,
            qualification.operational_evidence_hash == lease.operational_evidence_hash,
            qualification.renewal_lease_id == lease.prior_renewal_lease_id,
            qualification.renewal_lease_hash == lease.prior_renewal_lease_hash,
            qualification.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
            qualification.authorization_id == authorization.prior_renewal_authorization_id,
            qualification.authorization_hash == authorization.prior_renewal_authorization_hash,
            qualification.phase_n_health_qualification_id == authorization.phase_n_health_qualification_id,
            qualification.phase_n_health_qualification_hash == authorization.phase_n_health_qualification_hash,
            qualification.prior_durable_lease_id == authorization.prior_durable_lease_id,
            qualification.prior_durable_lease_hash == authorization.prior_durable_lease_hash,
            qualification.replica_id == lease.replica_id,
            qualification.replica_hash == lease.replica_hash,
            qualification.source_file_hash == lease.source_file_hash,
            qualification.source_file_size_bytes == lease.source_file_size_bytes,
            qualification.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            qualification.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            qualification.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            qualification.source_authority_fingerprint == lease.source_authority_fingerprint,
            qualification.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            qualification.configuration_fingerprint == lease.configuration_fingerprint,
            qualification.verified_durable_read_count == lease.verified_durable_read_count,
            qualification.integrity_failure_count == 0,
            qualification.storage_unavailable_count == 0,
            qualification.routable_authority_created is False,
            qualification.durable_read_route_created is False,
            qualification.read_path_switched is False,
            qualification.write_path_switched is False,
            qualification.document_storage_key_mutated is False,
            qualification.authoritative_storage_changed is False,
            qualification.destructive_action_performed is False,
            qualification.s3_delete_performed is False,
            qualification.local_delete_performed is False,
        )
    ):
        return False
    q_receipt = _qualified_q_receipt(db, qualification=qualification)
    return all(
        (
            q_receipt.id == authorization.phase_q_health_receipt_id,
            q_receipt.receipt_hash == authorization.phase_q_health_receipt_hash,
        )
    )


def _validate_active_reauthorized_renewal_read(
    db: Session,
    *,
    document: Document,
    route: EvidenceRecoveryReadPathRoute,
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    now: datetime,
) -> bytes:
    if not all(
        (
            lease.status == "activated",
            lease.routable_authority_created is True,
            lease.durable_read_route_created is True,
            lease.read_path_switched is True,
            lease.write_path_switched is False,
            lease.document_storage_key_mutated is False,
            lease.authoritative_storage_changed is False,
            lease.destructive_action_performed is False,
            lease.route_expires_at is not None,
            route.route_class == "recovery_replica",
            route.route_authority_kind == "durable_reauthorized_renewal",
            route.active_lease_id is None,
            route.active_durable_lease_id is None,
            route.active_durable_renewal_lease_id is None,
            route.active_durable_reauthorized_renewal_lease_id == lease.id,
            route.active_replica_id == lease.replica_id,
            route.route_version == lease.route_version_at_prepare + 1,
            route.read_path_switched is True,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.source_authority_fingerprint == lease.source_authority_fingerprint,
            route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            route.configuration_fingerprint == lease.configuration_fingerprint,
        )
    ):
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Active Phase S route is structurally inconsistent"
        )
    if now >= _as_utc(lease.route_expires_at):
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Active Phase S recovery route expired; reconciliation or rollback is required"
        )
    try:
        authorization = _get_reauthorization(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            authorization_id=lease.reauthorization_id,
        )
        if not all(
            (
                authorization.status == "approved",
                authorization.approved_by_id == lease.reauthorization_approved_by_id,
                authorization.authorization_hash == lease.reauthorization_hash,
                authorization.request_snapshot_hash == lease.reauthorization_request_snapshot_hash,
                authorization.integrity_proof_hash == lease.reauthorization_integrity_proof_hash,
                authorization.phase_q_health_qualification_id == lease.phase_q_health_qualification_id,
                authorization.renewal_lease_id == lease.prior_renewal_lease_id,
                authorization.replica_id == lease.replica_id,
                authorization.phase_q_health_qualification_hash == lease.phase_q_health_qualification_hash,
                authorization.operational_evidence_hash == lease.operational_evidence_hash,
                authorization.renewal_lease_hash == lease.prior_renewal_lease_hash,
                authorization.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
                authorization.replica_hash == lease.replica_hash,
                authorization.source_file_hash == lease.source_file_hash,
                authorization.source_file_size_bytes == lease.source_file_size_bytes,
                authorization.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
                authorization.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
                authorization.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
                authorization.source_authority_fingerprint == lease.source_authority_fingerprint,
                authorization.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
                authorization.configuration_fingerprint == lease.configuration_fingerprint,
                authorization.verified_durable_read_count == lease.verified_durable_read_count,
                authorization.integrity_failure_count == 0,
                authorization.storage_unavailable_count == 0,
                authorization.health_state == "healthy",
                authorization.routable_authority_created is False,
                authorization.durable_read_route_created is False,
                authorization.read_path_switched is False,
                authorization.write_path_switched is False,
                authorization.document_storage_key_mutated is False,
                authorization.authoritative_storage_changed is False,
                authorization.destructive_action_performed is False,
                authorization.s3_delete_performed is False,
                authorization.local_delete_performed is False,
            )
        ):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase R authorization lineage drifted after Phase S activation"
            )
        approval = _approval_receipt(db, authorization=authorization)
        if approval.id != lease.reauthorization_approval_receipt_id or approval.receipt_hash != lease.reauthorization_approval_receipt_hash:
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase R approval receipt drifted after Phase S activation"
            )
        if not _active_q_lineage_matches(db, lease=lease, authorization=authorization):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase Q/P governance lineage drifted after Phase S activation"
            )
        prior_renewal = _get_prior_renewal_lease(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            lease_id=lease.prior_renewal_lease_id,
        )
        if not _prior_renewal_matches_reauthorization(prior_renewal, authorization):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Prior Phase P lease lineage drifted after Phase S activation"
            )
        replica = _load_replica(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            replica_id=lease.replica_id,
        )
        local_snapshot = _snapshot_local(document)
        _assert_replica_matches_source(replica, local_snapshot)
        if not all(
            (
                local_snapshot.file_hash == lease.source_file_hash,
                local_snapshot.file_size_bytes == lease.source_file_size_bytes,
                local_snapshot.storage_key_fingerprint == lease.local_storage_key_fingerprint,
                replica.replica_hash == lease.replica_hash,
                replica.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
                hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
                == lease.candidate_storage_key_fingerprint,
            )
        ):
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Local or recovery replica lineage drifted after Phase S activation"
            )
        candidate_payload = _read_verified_candidate(replica)
        if hashlib.sha256(candidate_payload).hexdigest() != lease.source_file_hash or len(candidate_payload) != lease.source_file_size_bytes:
            raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
                "Phase S candidate bytes failed fresh integrity verification"
            )
        return candidate_payload
    except RecoveryDurableReadReauthorizedRenewalRoutingError:
        raise
    except RecoveryDurableReadRenewalReauthorizationNotFound as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalReauthorizationConflict as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalReauthorizationUnavailable as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(str(exc)) from exc
    except RecoveryDurableReadRenewalRoutingNotFound as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalRoutingConflict as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalRoutingUnavailable as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadReauthorizedRenewalRoutingUnavailable(str(exc)) from exc


def reconcile_recovery_durable_read_reauthorized_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    reconciled_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadReauthorizedRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadReauthorizedRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase S reconciliation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    if lease.status == "expired" and _route_is_clean_local(route):
        return lease, route, None, "unchanged"
    if lease.status != "activated" or lease.route_expires_at is None:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Only an activated Phase S lease can be reconciled"
        )
    if current_time >= _as_utc(lease.route_expires_at):
        receipt = _restore_local_route(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=reconciled_by_id,
            reason="Phase S operational window expired and was reconciled to local source",
            now=current_time,
        )
        return lease, route, receipt, "expired"
    document = _load_document(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    _validate_active_reauthorized_renewal_read(
        db,
        document=document,
        route=route,
        lease=lease,
        now=current_time,
    )
    return lease, route, None, "unchanged"


def resolve_recovery_document_read_reauthorized_renewal(
    db: Session,
    *,
    document: Document,
    now: datetime | None = None,
) -> tuple[bytes, str]:
    route = _get_route(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        required=True,
    )
    assert route is not None
    if route.route_authority_kind != "durable_reauthorized_renewal":
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Read route is not owned by a Phase S lease"
        )
    if route.active_durable_reauthorized_renewal_lease_id is None:
        raise RecoveryDurableReadReauthorizedRenewalRoutingConflict(
            "Phase S route has no active reauthorized renewal lease"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        lease_id=route.active_durable_reauthorized_renewal_lease_id,
    )
    payload = _validate_active_reauthorized_renewal_read(
        db,
        document=document,
        route=route,
        lease=lease,
        now=current_time,
    )
    return payload, "recovery-replica-durable-reauthorized-renewal"


def get_recovery_durable_read_reauthorized_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalLease:
    return _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )


def list_recovery_durable_read_reauthorized_renewal_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> list[EvidenceRecoveryDurableReadReauthorizedRenewalReceipt]:
    _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadReauthorizedRenewalReceipt)
            .where(
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.reauthorized_renewal_lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.id.asc(),
            )
        ).all()
    )
