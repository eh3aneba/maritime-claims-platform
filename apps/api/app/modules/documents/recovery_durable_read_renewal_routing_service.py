from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_health_service import (
    RecoveryDurableReadHealthConflict,
    RecoveryDurableReadHealthNotFound,
    _get_qualification as _get_health_qualification,
)
from app.modules.documents.recovery_durable_read_renewal_models import (
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_routing_models import (
    EvidenceRecoveryDurableReadRenewalLease,
    EvidenceRecoveryDurableReadRenewalReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_service import (
    RecoveryDurableReadRenewalAuthorizationConflict,
    RecoveryDurableReadRenewalAuthorizationNotFound,
    RecoveryDurableReadRenewalAuthorizationUnavailable,
    _get_authorization,
    _load_snapshot as _load_authorization_snapshot,
    _matches_snapshot as _matches_authorization_snapshot,
)
from app.modules.documents.recovery_durable_read_routing_models import (
    EvidenceRecoveryDurableReadPromotionLease,
)
from app.modules.documents.recovery_durable_read_routing_service import (
    RecoveryDurableReadRoutingConflict,
    RecoveryDurableReadRoutingNotFound,
    RecoveryDurableReadRoutingUnavailable,
    _get_lease as _get_prior_durable_lease,
    _get_route,
    _load_document,
    _load_replica,
    _read_verified_candidate,
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
)

DURABLE_READ_RENEWAL_ROUTE_WINDOW = timedelta(hours=24)


class RecoveryDurableReadRenewalRoutingError(RuntimeError):
    pass


class RecoveryDurableReadRenewalRoutingNotFound(RecoveryDurableReadRenewalRoutingError):
    pass


class RecoveryDurableReadRenewalRoutingConflict(RecoveryDurableReadRenewalRoutingError):
    pass


class RecoveryDurableReadRenewalRoutingUnavailable(RecoveryDurableReadRenewalRoutingError):
    pass


@dataclass(frozen=True)
class DurableReadRenewalRoutingSnapshot:
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    health_qualification_id: UUID
    prior_durable_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_integrity_proof_hash: str
    authorization_approval_receipt_hash: str
    health_qualification_hash: str
    operational_evidence_hash: str
    prior_durable_lease_hash: str
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
    authorization_approved_by_id: UUID
    prior_durable_activated_by_id: UUID
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
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization,
) -> EvidenceRecoveryDurableReadRenewalAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalAuthorizationReceipt).where(
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.organization_id
                == authorization.organization_id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.claim_id
                == authorization.claim_id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.document_id
                == authorization.document_id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.authorization_id
                == authorization.id,
                EvidenceRecoveryDurableReadRenewalAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Approved Phase O authorization must have exactly one approval receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.health_qualification_id == authorization.health_qualification_id,
            receipt.durable_lease_id == authorization.durable_lease_id,
            receipt.health_qualification_hash == authorization.health_qualification_hash,
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
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Phase O approval receipt lineage is inconsistent"
        )
    return receipt


def _prior_lease_matches_authorization(
    lease: EvidenceRecoveryDurableReadPromotionLease,
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization,
) -> bool:
    return all(
        (
            lease.id == authorization.durable_lease_id,
            lease.status in {"rolled_back", "expired"},
            lease.activated_by_id == authorization.durable_activated_by_id,
            lease.lease_hash == authorization.durable_lease_hash,
            lease.lease_snapshot_hash == authorization.lease_snapshot_hash,
            lease.replica_id == authorization.replica_id,
            lease.replica_hash == authorization.replica_hash,
            lease.source_file_hash == authorization.source_file_hash,
            lease.source_file_size_bytes == authorization.source_file_size_bytes,
            lease.local_storage_key_fingerprint
            == authorization.local_storage_key_fingerprint,
            lease.recovery_bucket_fingerprint
            == authorization.recovery_bucket_fingerprint,
            lease.candidate_storage_key_fingerprint
            == authorization.candidate_storage_key_fingerprint,
            lease.source_authority_fingerprint
            == authorization.source_authority_fingerprint,
            lease.candidate_authority_fingerprint
            == authorization.candidate_authority_fingerprint,
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
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization,
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
            hashlib.sha256(candidate_payload).hexdigest()
            == authorization.source_file_hash,
            len(candidate_payload) == authorization.source_file_size_bytes,
        )
    ):
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Fresh local or recovery candidate integrity does not match Phase O"
        )
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "health_qualification_id": str(authorization.health_qualification_id),
            "prior_durable_lease_id": str(authorization.durable_lease_id),
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
    authorization_id: UUID,
    now: datetime | None = None,
) -> DurableReadRenewalRoutingSnapshot:
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
                authorization.health_state == "healthy",
                authorization.verified_durable_read_count >= 1,
                authorization.integrity_failure_count == 0,
                authorization.storage_unavailable_count == 0,
            )
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Only an approved healthy Phase O authorization can prepare renewal routing"
            )
        if current_time >= _as_utc(authorization.authorization_expires_at):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Approved Phase O authorization is outside its activation window"
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
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Phase O authorization crossed its non-routable safety boundary"
            )

        authorization_snapshot = _load_authorization_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=authorization.health_qualification_id,
        )
        if not _matches_authorization_snapshot(authorization, authorization_snapshot):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Phase O authorization lineage drifted before renewal preparation"
            )
        approval = _approval_receipt(db, authorization=authorization)
        prior_lease = _get_prior_durable_lease(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=authorization.durable_lease_id,
        )
        if not _prior_lease_matches_authorization(prior_lease, authorization):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Prior Phase M lease lineage no longer matches Phase O"
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
            and route.source_authority_fingerprint
            == authorization.source_authority_fingerprint
            and route.candidate_authority_fingerprint
            == authorization.candidate_authority_fingerprint
            and route.configuration_fingerprint
            == authorization.configuration_fingerprint
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Single read-route control plane is not in the Phase O pinned local state"
            )
        integrity_proof_hash = _fresh_source_and_candidate_proof(
            db,
            authorization=authorization,
        )
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
                "health_qualification_id": str(authorization.health_qualification_id),
                "health_qualification_hash": authorization.health_qualification_hash,
                "operational_evidence_hash": authorization.operational_evidence_hash,
                "prior_durable_lease_id": str(authorization.durable_lease_id),
                "prior_durable_lease_hash": authorization.durable_lease_hash,
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
                "mode": "bounded_reversible_durable_read_renewal_routing",
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return DurableReadRenewalRoutingSnapshot(
            authorization_id=authorization.id,
            authorization_approval_receipt_id=approval.id,
            health_qualification_id=authorization.health_qualification_id,
            prior_durable_lease_id=authorization.durable_lease_id,
            replica_id=authorization.replica_id,
            authorization_hash=authorization.authorization_hash,
            authorization_request_snapshot_hash=authorization.request_snapshot_hash,
            authorization_integrity_proof_hash=authorization.integrity_proof_hash,
            authorization_approval_receipt_hash=approval.receipt_hash,
            health_qualification_hash=authorization.health_qualification_hash,
            operational_evidence_hash=authorization.operational_evidence_hash,
            prior_durable_lease_hash=authorization.durable_lease_hash,
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
            authorization_approved_by_id=authorization.approved_by_id,
            prior_durable_activated_by_id=authorization.durable_activated_by_id,
            authorization_expires_at=_as_utc(authorization.authorization_expires_at),
        )
    except RecoveryDurableReadRenewalRoutingError:
        raise
    except RecoveryDurableReadRenewalAuthorizationNotFound as exc:
        raise RecoveryDurableReadRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalAuthorizationConflict as exc:
        raise RecoveryDurableReadRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalAuthorizationUnavailable as exc:
        raise RecoveryDurableReadRenewalRoutingUnavailable(str(exc)) from exc
    except RecoveryDurableReadRoutingNotFound as exc:
        raise RecoveryDurableReadRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRoutingConflict as exc:
        raise RecoveryDurableReadRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRoutingUnavailable as exc:
        raise RecoveryDurableReadRenewalRoutingUnavailable(str(exc)) from exc
    except (RecoveryRoutableReadCutoverNotFound, RecoveryDurableReadHealthNotFound) as exc:
        raise RecoveryDurableReadRenewalRoutingNotFound(str(exc)) from exc
    except (
        RecoveryRoutableReadCutoverConflict,
        RecoveryReplicationConflict,
        RecoveryDurableReadHealthConflict,
    ) as exc:
        raise RecoveryDurableReadRenewalRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadRenewalRoutingUnavailable(str(exc)) from exc


def _matches_snapshot(
    lease: EvidenceRecoveryDurableReadRenewalLease,
    snapshot: DurableReadRenewalRoutingSnapshot,
) -> bool:
    return all(
        (
            lease.authorization_id == snapshot.authorization_id,
            lease.authorization_approval_receipt_id
            == snapshot.authorization_approval_receipt_id,
            lease.health_qualification_id == snapshot.health_qualification_id,
            lease.prior_durable_lease_id == snapshot.prior_durable_lease_id,
            lease.replica_id == snapshot.replica_id,
            lease.authorization_hash == snapshot.authorization_hash,
            lease.authorization_request_snapshot_hash
            == snapshot.authorization_request_snapshot_hash,
            lease.authorization_integrity_proof_hash
            == snapshot.authorization_integrity_proof_hash,
            lease.authorization_approval_receipt_hash
            == snapshot.authorization_approval_receipt_hash,
            lease.health_qualification_hash == snapshot.health_qualification_hash,
            lease.operational_evidence_hash == snapshot.operational_evidence_hash,
            lease.prior_durable_lease_hash == snapshot.prior_durable_lease_hash,
            lease.prior_lease_snapshot_hash == snapshot.prior_lease_snapshot_hash,
            lease.replica_hash == snapshot.replica_hash,
            lease.source_file_hash == snapshot.source_file_hash,
            lease.source_file_size_bytes == snapshot.source_file_size_bytes,
            lease.local_storage_key_fingerprint
            == snapshot.local_storage_key_fingerprint,
            lease.recovery_bucket_fingerprint
            == snapshot.recovery_bucket_fingerprint,
            lease.candidate_storage_key_fingerprint
            == snapshot.candidate_storage_key_fingerprint,
            lease.source_authority_fingerprint
            == snapshot.source_authority_fingerprint,
            lease.candidate_authority_fingerprint
            == snapshot.candidate_authority_fingerprint,
            lease.configuration_fingerprint == snapshot.configuration_fingerprint,
            lease.verified_durable_read_count == snapshot.verified_durable_read_count,
            lease.integrity_failure_count == snapshot.integrity_failure_count,
            lease.storage_unavailable_count == snapshot.storage_unavailable_count,
            lease.route_version_at_prepare == snapshot.route_version_at_prepare,
            lease.integrity_proof_hash == snapshot.integrity_proof_hash,
            lease.lease_snapshot_hash == snapshot.lease_snapshot_hash,
            lease.authorization_approved_by_id
            == snapshot.authorization_approved_by_id,
            lease.prior_durable_activated_by_id
            == snapshot.prior_durable_activated_by_id,
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
) -> EvidenceRecoveryDurableReadRenewalLease:
    stmt = select(EvidenceRecoveryDurableReadRenewalLease).where(
        EvidenceRecoveryDurableReadRenewalLease.id == lease_id,
        EvidenceRecoveryDurableReadRenewalLease.organization_id == organization_id,
        EvidenceRecoveryDurableReadRenewalLease.claim_id == claim_id,
        EvidenceRecoveryDurableReadRenewalLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryDurableReadRenewalRoutingNotFound(
            "Recovery durable read renewal lease not found"
        )
    return lease


def _new_receipt(
    *,
    lease: EvidenceRecoveryDurableReadRenewalLease,
    phase: str,
    from_route_class: str,
    to_route_class: str,
    route_authority_kind: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadRenewalReceipt:
    normalized_reason = reason.strip()
    switched = to_route_class == "recovery_replica" and route_authority_kind == "durable_renewal"
    receipt_hash = _canonical_hash(
        {
            "renewal_lease_id": str(lease.id),
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
            "read_path_switched": switched,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryDurableReadRenewalReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        renewal_lease_id=lease.id,
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
    lease: EvidenceRecoveryDurableReadRenewalLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadRenewalReceipt:
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


def prepare_recovery_durable_read_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Durable read renewal lease preparation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_preparation_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalLease)
        .where(
            EvidenceRecoveryDurableReadRenewalLease.organization_id == organization_id,
            EvidenceRecoveryDurableReadRenewalLease.claim_id == claim_id,
            EvidenceRecoveryDurableReadRenewalLease.document_id == document_id,
            EvidenceRecoveryDurableReadRenewalLease.authorization_id == authorization_id,
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
        if not (
            existing.prepared_by_id == prepared_by_id
            and existing.preparation_reason == normalized_reason
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Renewal lease already exists with different preparation semantics"
            )
        if _matches_snapshot(existing, snapshot):
            if existing.status == "prepared" and _route_is_clean_local(route):
                return existing, route, None, "unchanged"
            if existing.status == "activated":
                if not (
                    route.route_class == "recovery_replica"
                    and route.route_authority_kind == "durable_renewal"
                    and route.active_lease_id is None
                    and route.active_durable_lease_id is None
                    and route.active_durable_renewal_lease_id == existing.id
                    and route.active_replica_id == existing.replica_id
                ):
                    raise RecoveryDurableReadRenewalRoutingConflict(
                        "Activated renewal lease no longer matches the read-route record"
                    )
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
                reason="Durable read renewal lineage drifted before preparation replay",
                now=current_time,
            )
            return existing, route, receipt, "invalidated"
        raise RecoveryDurableReadRenewalRoutingConflict(
            "A terminal renewal lease already exists for this authorization"
        )
    if not _route_is_clean_local(route):
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Another temporary or durable read authority is already active"
        )
    if route.route_version != snapshot.route_version_at_prepare:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Read route version drifted before renewal lease creation"
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
            "max_route_window_seconds": int(DURABLE_READ_RENEWAL_ROUTE_WINDOW.total_seconds()),
            "mode": "bounded_reversible_durable_read_renewal_lease",
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    lease = EvidenceRecoveryDurableReadRenewalLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=snapshot.authorization_id,
        authorization_approval_receipt_id=snapshot.authorization_approval_receipt_id,
        health_qualification_id=snapshot.health_qualification_id,
        prior_durable_lease_id=snapshot.prior_durable_lease_id,
        replica_id=snapshot.replica_id,
        authorization_hash=snapshot.authorization_hash,
        authorization_request_snapshot_hash=snapshot.authorization_request_snapshot_hash,
        authorization_integrity_proof_hash=snapshot.authorization_integrity_proof_hash,
        authorization_approval_receipt_hash=snapshot.authorization_approval_receipt_hash,
        health_qualification_hash=snapshot.health_qualification_hash,
        operational_evidence_hash=snapshot.operational_evidence_hash,
        prior_durable_lease_hash=snapshot.prior_durable_lease_hash,
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
        authorization_approved_by_id=snapshot.authorization_approved_by_id,
        prior_durable_activated_by_id=snapshot.prior_durable_activated_by_id,
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


def activate_recovery_durable_read_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Durable read renewal activation reason is required"
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
        if not (
            lease.activated_by_id == activated_by_id
            and lease.activation_reason == normalized_reason
            and route.route_class == "recovery_replica"
            and route.route_authority_kind == "durable_renewal"
            and route.active_lease_id is None
            and route.active_durable_lease_id is None
            and route.active_durable_renewal_lease_id == lease.id
            and route.active_replica_id == lease.replica_id
            and route.read_path_switched is True
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Renewal activation replay does not match active authority"
            )
        return lease, route, None, "unchanged"
    if lease.status != "prepared":
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Only a prepared durable read renewal lease can be activated"
        )
    if lease.prepared_by_id == activated_by_id:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Renewal activation requires a different Admin from the preparer"
        )
    if lease.authorization_approved_by_id == activated_by_id:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Renewal activator must differ from the Phase O approver"
        )
    if lease.prior_durable_activated_by_id == activated_by_id:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Renewal activator must differ from the prior Phase M activator"
        )
    if current_time >= _as_utc(lease.activation_expires_at):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=activated_by_id,
            reason="Durable read renewal activation window expired",
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
    except RecoveryDurableReadRenewalRoutingUnavailable:
        raise
    except (RecoveryDurableReadRenewalRoutingConflict, RecoveryDurableReadRenewalRoutingNotFound) as exc:
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh durable read renewal preflight failed: {type(exc).__name__}",
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
            reason="Durable read renewal lineage or route drifted before activation",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"

    lease.status = "activated"
    lease.activated_by_id = activated_by_id
    lease.activated_at = current_time
    lease.activation_reason = normalized_reason
    lease.route_expires_at = current_time + DURABLE_READ_RENEWAL_ROUTE_WINDOW
    lease.routable_authority_created = True
    lease.durable_read_route_created = True
    lease.read_path_switched = True

    route.route_class = "recovery_replica"
    route.route_authority_kind = "durable_renewal"
    route.active_lease_id = None
    route.active_durable_lease_id = None
    route.active_durable_renewal_lease_id = lease.id
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
        route_authority_kind="durable_renewal",
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
    lease: EvidenceRecoveryDurableReadRenewalLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadRenewalReceipt:
    if not (
        route.route_class == "recovery_replica"
        and route.route_authority_kind == "durable_renewal"
        and route.active_lease_id is None
        and route.active_durable_lease_id is None
        and route.active_durable_renewal_lease_id == lease.id
        and route.active_replica_id == lease.replica_id
        and route.read_path_switched is True
    ):
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Active read route does not match the renewal lease being restored"
        )
    route.route_class = "local_source"
    route.route_authority_kind = "local"
    route.active_lease_id = None
    route.active_durable_lease_id = None
    route.active_durable_renewal_lease_id = None
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


def rollback_recovery_durable_read_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Durable read renewal rollback reason is required"
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
    if lease.status == "rolled_back":
        if not (
            lease.rolled_back_by_id == rolled_back_by_id
            and lease.rollback_reason == normalized_reason
            and _route_is_clean_local(route)
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Renewal rollback replay does not match the original rollback"
            )
        return lease, route, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Only an activated durable read renewal lease can be rolled back"
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


def _validate_active_renewal_read(
    db: Session,
    *,
    document: Document,
    route: EvidenceRecoveryReadPathRoute,
    lease: EvidenceRecoveryDurableReadRenewalLease,
    now: datetime,
) -> bytes:
    if not (
        lease.status == "activated"
        and lease.routable_authority_created is True
        and lease.durable_read_route_created is True
        and lease.read_path_switched is True
        and lease.write_path_switched is False
        and lease.document_storage_key_mutated is False
        and lease.authoritative_storage_changed is False
        and lease.destructive_action_performed is False
        and lease.route_expires_at is not None
        and route.route_class == "recovery_replica"
        and route.route_authority_kind == "durable_renewal"
        and route.active_lease_id is None
        and route.active_durable_lease_id is None
        and route.active_durable_renewal_lease_id == lease.id
        and route.active_replica_id == lease.replica_id
        and route.route_version == lease.route_version_at_prepare + 1
        and route.read_path_switched is True
        and route.write_path_switched is False
        and route.document_storage_key_mutated is False
        and route.authoritative_storage_changed is False
        and route.destructive_action_performed is False
        and route.source_authority_fingerprint == lease.source_authority_fingerprint
        and route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint
        and route.configuration_fingerprint == lease.configuration_fingerprint
    ):
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Active durable renewal route is structurally inconsistent"
        )
    if now >= _as_utc(lease.route_expires_at):
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Active durable recovery renewal route expired; reconciliation or rollback is required"
        )
    try:
        authorization = _get_authorization(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            authorization_id=lease.authorization_id,
        )
        if not all(
            (
                authorization.status == "approved",
                authorization.approved_by_id == lease.authorization_approved_by_id,
                authorization.authorization_hash == lease.authorization_hash,
                authorization.request_snapshot_hash
                == lease.authorization_request_snapshot_hash,
                authorization.integrity_proof_hash
                == lease.authorization_integrity_proof_hash,
                authorization.health_qualification_id == lease.health_qualification_id,
                authorization.durable_lease_id == lease.prior_durable_lease_id,
                authorization.replica_id == lease.replica_id,
                authorization.health_qualification_hash
                == lease.health_qualification_hash,
                authorization.operational_evidence_hash
                == lease.operational_evidence_hash,
                authorization.durable_lease_hash == lease.prior_durable_lease_hash,
                authorization.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
                authorization.replica_hash == lease.replica_hash,
                authorization.source_file_hash == lease.source_file_hash,
                authorization.source_file_size_bytes == lease.source_file_size_bytes,
                authorization.local_storage_key_fingerprint
                == lease.local_storage_key_fingerprint,
                authorization.recovery_bucket_fingerprint
                == lease.recovery_bucket_fingerprint,
                authorization.candidate_storage_key_fingerprint
                == lease.candidate_storage_key_fingerprint,
                authorization.source_authority_fingerprint
                == lease.source_authority_fingerprint,
                authorization.candidate_authority_fingerprint
                == lease.candidate_authority_fingerprint,
                authorization.configuration_fingerprint
                == lease.configuration_fingerprint,
                authorization.verified_durable_read_count
                == lease.verified_durable_read_count,
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
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Phase O authorization lineage drifted after renewal activation"
            )
        approval = _approval_receipt(db, authorization=authorization)
        if (
            approval.id != lease.authorization_approval_receipt_id
            or approval.receipt_hash != lease.authorization_approval_receipt_hash
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Phase O approval receipt drifted after renewal activation"
            )
        health = _get_health_qualification(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            health_qualification_id=lease.health_qualification_id,
        )
        if not all(
            (
                health.status == "qualified",
                health.health_state == "healthy",
                health.health_qualification_hash == lease.health_qualification_hash,
                health.operational_evidence_hash == lease.operational_evidence_hash,
                health.durable_lease_id == lease.prior_durable_lease_id,
                health.replica_id == lease.replica_id,
                health.verified_durable_read_count == lease.verified_durable_read_count,
                health.integrity_failure_count == 0,
                health.storage_unavailable_count == 0,
            )
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Phase N health qualification lineage drifted after renewal activation"
            )
        prior_lease = _get_prior_durable_lease(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            lease_id=lease.prior_durable_lease_id,
        )
        if not _prior_lease_matches_authorization(prior_lease, authorization):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Prior Phase M lease lineage drifted after renewal activation"
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
        if not (
            local_snapshot.file_hash == lease.source_file_hash
            and local_snapshot.file_size_bytes == lease.source_file_size_bytes
            and local_snapshot.storage_key_fingerprint
            == lease.local_storage_key_fingerprint
            and replica.replica_hash == lease.replica_hash
            and replica.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint
            and hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
            == lease.candidate_storage_key_fingerprint
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Local or recovery replica lineage drifted after renewal activation"
            )
        candidate_payload = _read_verified_candidate(replica)
        if (
            hashlib.sha256(candidate_payload).hexdigest() != lease.source_file_hash
            or len(candidate_payload) != lease.source_file_size_bytes
        ):
            raise RecoveryDurableReadRenewalRoutingConflict(
                "Durable renewal candidate bytes failed fresh integrity verification"
            )
        return candidate_payload
    except RecoveryDurableReadRenewalRoutingError:
        raise
    except RecoveryDurableReadRenewalAuthorizationNotFound as exc:
        raise RecoveryDurableReadRenewalRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadRenewalAuthorizationConflict as exc:
        raise RecoveryDurableReadRenewalRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadRenewalAuthorizationUnavailable as exc:
        raise RecoveryDurableReadRenewalRoutingUnavailable(str(exc)) from exc
    except (RecoveryDurableReadRoutingNotFound, RecoveryDurableReadHealthNotFound, RecoveryRoutableReadCutoverNotFound) as exc:
        raise RecoveryDurableReadRenewalRoutingNotFound(str(exc)) from exc
    except (RecoveryDurableReadRoutingConflict, RecoveryDurableReadHealthConflict, RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict) as exc:
        raise RecoveryDurableReadRenewalRoutingConflict(str(exc)) from exc
    except (RecoveryDurableReadRoutingUnavailable, RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadRenewalRoutingUnavailable(str(exc)) from exc


def reconcile_recovery_durable_read_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    reconciled_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalLease, EvidenceRecoveryReadPathRoute, EvidenceRecoveryDurableReadRenewalReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Durable read renewal reconciliation reason is required"
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
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Only an activated durable read renewal lease can be reconciled"
        )
    if current_time >= _as_utc(lease.route_expires_at):
        receipt = _restore_local_route(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=reconciled_by_id,
            reason="Durable read renewal operational window expired and was reconciled to local source",
            now=current_time,
        )
        return lease, route, receipt, "expired"
    document = _load_document(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    _validate_active_renewal_read(
        db,
        document=document,
        route=route,
        lease=lease,
        now=current_time,
    )
    return lease, route, None, "unchanged"


def resolve_recovery_document_read_renewal(
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
    if route.route_authority_kind != "durable_renewal":
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Read route is not owned by a durable renewal lease"
        )
    if route.active_durable_renewal_lease_id is None:
        raise RecoveryDurableReadRenewalRoutingConflict(
            "Durable renewal route has no active renewal lease"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        lease_id=route.active_durable_renewal_lease_id,
    )
    payload = _validate_active_renewal_read(
        db,
        document=document,
        route=route,
        lease=lease,
        now=current_time,
    )
    return payload, "recovery-replica-durable-renewal"


def get_recovery_durable_read_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryDurableReadRenewalLease:
    return _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )


def list_recovery_durable_read_renewal_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> list[EvidenceRecoveryDurableReadRenewalReceipt]:
    _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalReceipt)
            .where(
                EvidenceRecoveryDurableReadRenewalReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableReadRenewalReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadRenewalReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadRenewalReceipt.renewal_lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadRenewalReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadRenewalReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadRenewalReceipt.id.asc(),
            )
        ).all()
    )
