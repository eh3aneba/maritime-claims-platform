from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_promotion_models import (
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt,
)
from app.modules.documents.recovery_durable_read_promotion_service import (
    RecoveryDurableReadPromotionAuthorizationConflict,
    RecoveryDurableReadPromotionAuthorizationNotFound,
    RecoveryDurableReadPromotionAuthorizationUnavailable,
    _get_authorization,
    _load_snapshot as _load_authorization_snapshot,
    _matches_snapshot as _matches_authorization_snapshot,
)
from app.modules.documents.recovery_durable_read_routing_models import (
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryDurableReadPromotionReceipt,
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
    resolve_recovery_document_read as resolve_temporary_recovery_document_read,
)
from app.modules.documents.recovery_routable_read_qualification_service import _get_qualification

DURABLE_READ_ROUTE_WINDOW = timedelta(hours=24)


class RecoveryDurableReadRoutingError(RuntimeError):
    pass


class RecoveryDurableReadRoutingNotFound(RecoveryDurableReadRoutingError):
    pass


class RecoveryDurableReadRoutingConflict(RecoveryDurableReadRoutingError):
    pass


class RecoveryDurableReadRoutingUnavailable(RecoveryDurableReadRoutingError):
    pass


@dataclass(frozen=True)
class DurableReadRoutingSnapshot:
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    qualification_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_integrity_proof_hash: str
    authorization_approval_receipt_hash: str
    qualification_hash: str
    qualification_bundle_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    route_version_at_prepare: int
    lease_snapshot_hash: str
    authorization_approved_by_id: UUID
    authorization_expires_at: datetime
    candidate_payload: bytes


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approval_receipt(
    db: Session,
    *,
    authorization: EvidenceRecoveryDurableReadPromotionAuthorization,
) -> EvidenceRecoveryDurableReadPromotionAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadPromotionAuthorizationReceipt).where(
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.organization_id
                == authorization.organization_id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.claim_id
                == authorization.claim_id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.document_id
                == authorization.document_id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.authorization_id
                == authorization.id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadRoutingConflict(
            "Approved durable read promotion authorization must have exactly one approval receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.qualification_id == authorization.qualification_id,
            receipt.qualification_hash == authorization.qualification_hash,
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
        raise RecoveryDurableReadRoutingConflict(
            "Durable read promotion authorization approval receipt lineage is inconsistent"
        )
    return receipt


def _load_preparation_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
) -> DurableReadRoutingSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        authorization = _get_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
        if (
            authorization.status != "approved"
            or authorization.approved_by_id is None
            or authorization.approved_at is None
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Only an approved Phase L authorization can prepare durable read routing"
            )
        if current_time >= _as_utc(authorization.authorization_expires_at):
            raise RecoveryDurableReadRoutingConflict(
                "Approved Phase L authorization is outside its activation window"
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
            raise RecoveryDurableReadRoutingConflict(
                "Phase L authorization crossed its non-routable safety boundary"
            )

        authorization_snapshot = _load_authorization_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=authorization.qualification_id,
        )
        if not _matches_authorization_snapshot(authorization, authorization_snapshot):
            raise RecoveryDurableReadRoutingConflict(
                "Phase L authorization lineage drifted before durable routing preparation"
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
            route.route_class == "local_source"
            and route.route_authority_kind == "local"
            and route.active_lease_id is None
            and route.active_durable_lease_id is None
            and route.active_replica_id is None
            and route.read_path_switched is False
            and route.write_path_switched is False
            and route.document_storage_key_mutated is False
            and route.authoritative_storage_changed is False
            and route.destructive_action_performed is False
            and route.route_version == authorization.route_version_at_request
            and route.source_authority_fingerprint
            == authorization.source_authority_fingerprint
            and route.candidate_authority_fingerprint
            == authorization.candidate_authority_fingerprint
            and route.configuration_fingerprint == authorization.configuration_fingerprint
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Single read-route control plane is not in the pinned local state"
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
                "qualification_id": str(authorization.qualification_id),
                "qualification_hash": authorization.qualification_hash,
                "qualification_bundle_hash": authorization.qualification_bundle_hash,
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
                "route_version_at_prepare": route.route_version,
                "mode": "bounded_reversible_durable_read_routing",
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return DurableReadRoutingSnapshot(
            authorization_id=authorization.id,
            authorization_approval_receipt_id=approval.id,
            qualification_id=authorization.qualification_id,
            replica_id=authorization.replica_id,
            authorization_hash=authorization.authorization_hash,
            authorization_request_snapshot_hash=authorization.request_snapshot_hash,
            authorization_integrity_proof_hash=authorization.integrity_proof_hash,
            authorization_approval_receipt_hash=approval.receipt_hash,
            qualification_hash=authorization.qualification_hash,
            qualification_bundle_hash=authorization.qualification_bundle_hash,
            replica_hash=authorization.replica_hash,
            source_file_hash=authorization.source_file_hash,
            source_file_size_bytes=authorization.source_file_size_bytes,
            local_storage_key_fingerprint=authorization.local_storage_key_fingerprint,
            recovery_bucket_fingerprint=authorization.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=authorization.candidate_storage_key_fingerprint,
            source_authority_fingerprint=authorization.source_authority_fingerprint,
            candidate_authority_fingerprint=authorization.candidate_authority_fingerprint,
            configuration_fingerprint=authorization.configuration_fingerprint,
            route_version_at_prepare=route.route_version,
            lease_snapshot_hash=lease_snapshot_hash,
            authorization_approved_by_id=authorization.approved_by_id,
            authorization_expires_at=_as_utc(authorization.authorization_expires_at),
            candidate_payload=b"",
        )
    except RecoveryDurableReadRoutingError:
        raise
    except RecoveryDurableReadPromotionAuthorizationNotFound as exc:
        raise RecoveryDurableReadRoutingNotFound(str(exc)) from exc
    except RecoveryDurableReadPromotionAuthorizationConflict as exc:
        raise RecoveryDurableReadRoutingConflict(str(exc)) from exc
    except RecoveryDurableReadPromotionAuthorizationUnavailable as exc:
        raise RecoveryDurableReadRoutingUnavailable(str(exc)) from exc


def _matches_snapshot(
    lease: EvidenceRecoveryDurableReadPromotionLease,
    snapshot: DurableReadRoutingSnapshot,
) -> bool:
    return all(
        (
            lease.authorization_id == snapshot.authorization_id,
            lease.authorization_approval_receipt_id
            == snapshot.authorization_approval_receipt_id,
            lease.qualification_id == snapshot.qualification_id,
            lease.replica_id == snapshot.replica_id,
            lease.authorization_hash == snapshot.authorization_hash,
            lease.authorization_request_snapshot_hash
            == snapshot.authorization_request_snapshot_hash,
            lease.authorization_integrity_proof_hash
            == snapshot.authorization_integrity_proof_hash,
            lease.authorization_approval_receipt_hash
            == snapshot.authorization_approval_receipt_hash,
            lease.qualification_hash == snapshot.qualification_hash,
            lease.qualification_bundle_hash == snapshot.qualification_bundle_hash,
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
            lease.route_version_at_prepare == snapshot.route_version_at_prepare,
            lease.lease_snapshot_hash == snapshot.lease_snapshot_hash,
            lease.authorization_approved_by_id
            == snapshot.authorization_approved_by_id,
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
) -> EvidenceRecoveryDurableReadPromotionLease:
    stmt = select(EvidenceRecoveryDurableReadPromotionLease).where(
        EvidenceRecoveryDurableReadPromotionLease.id == lease_id,
        EvidenceRecoveryDurableReadPromotionLease.organization_id == organization_id,
        EvidenceRecoveryDurableReadPromotionLease.claim_id == claim_id,
        EvidenceRecoveryDurableReadPromotionLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryDurableReadRoutingNotFound(
            "Recovery durable read promotion lease not found"
        )
    return lease


def _new_receipt(
    *,
    lease: EvidenceRecoveryDurableReadPromotionLease,
    phase: str,
    from_route_class: str,
    to_route_class: str,
    route_authority_kind: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadPromotionReceipt:
    normalized_reason = reason.strip()
    switched = to_route_class == "recovery_replica"
    receipt_hash = _canonical_hash(
        {
            "durable_lease_id": str(lease.id),
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
    return EvidenceRecoveryDurableReadPromotionReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        durable_lease_id=lease.id,
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


def _route_is_clean_local(route: EvidenceRecoveryReadPathRoute) -> bool:
    return all(
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
        )
    )


def _route_matches_lease(
    route: EvidenceRecoveryReadPathRoute,
    lease: EvidenceRecoveryDurableReadPromotionLease,
) -> bool:
    return all(
        (
            route.source_authority_fingerprint == lease.source_authority_fingerprint,
            route.candidate_authority_fingerprint
            == lease.candidate_authority_fingerprint,
            route.configuration_fingerprint == lease.configuration_fingerprint,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
        )
    )


def _terminalize_prepared(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadPromotionLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadPromotionReceipt:
    if not _route_is_clean_local(route):
        raise RecoveryDurableReadRoutingConflict(
            "Prepared durable read lease cannot terminalize while another read authority is active"
        )
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


def prepare_recovery_durable_read_promotion_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryDurableReadPromotionReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRoutingConflict(
            "Durable read routing lease preparation reason is required"
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
        select(EvidenceRecoveryDurableReadPromotionLease)
        .where(
            EvidenceRecoveryDurableReadPromotionLease.organization_id == organization_id,
            EvidenceRecoveryDurableReadPromotionLease.claim_id == claim_id,
            EvidenceRecoveryDurableReadPromotionLease.document_id == document_id,
            EvidenceRecoveryDurableReadPromotionLease.authorization_id == authorization_id,
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
            raise RecoveryDurableReadRoutingConflict(
                "Durable read routing lease already exists with different preparation semantics"
            )
        if _matches_snapshot(existing, snapshot):
            if existing.status == "prepared" and _route_is_clean_local(route):
                return existing, route, None, "unchanged"
            if existing.status == "activated":
                if not (
                    route.route_class == "recovery_replica"
                    and route.route_authority_kind == "durable_promotion"
                    and route.active_lease_id is None
                    and route.active_durable_lease_id == existing.id
                    and route.active_replica_id == existing.replica_id
                    and _route_matches_lease(route, existing)
                ):
                    raise RecoveryDurableReadRoutingConflict(
                        "Activated durable lease no longer matches the single read-route record"
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
                reason="Durable read routing lineage drifted before preparation replay",
                now=current_time,
            )
            return existing, route, receipt, "invalidated"
        raise RecoveryDurableReadRoutingConflict(
            "A terminal durable read routing lease already exists for this authorization"
        )
    if not _route_is_clean_local(route):
        raise RecoveryDurableReadRoutingConflict(
            "Another temporary or durable read authority is already active"
        )
    if route.route_version != snapshot.route_version_at_prepare:
        raise RecoveryDurableReadRoutingConflict(
            "Read route version drifted before durable lease creation"
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
            "max_route_window_seconds": int(DURABLE_READ_ROUTE_WINDOW.total_seconds()),
            "mode": "bounded_reversible_durable_read_routing_lease",
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    lease = EvidenceRecoveryDurableReadPromotionLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=snapshot.authorization_id,
        authorization_approval_receipt_id=snapshot.authorization_approval_receipt_id,
        qualification_id=snapshot.qualification_id,
        replica_id=snapshot.replica_id,
        authorization_hash=snapshot.authorization_hash,
        authorization_request_snapshot_hash=snapshot.authorization_request_snapshot_hash,
        authorization_integrity_proof_hash=snapshot.authorization_integrity_proof_hash,
        authorization_approval_receipt_hash=snapshot.authorization_approval_receipt_hash,
        qualification_hash=snapshot.qualification_hash,
        qualification_bundle_hash=snapshot.qualification_bundle_hash,
        replica_hash=snapshot.replica_hash,
        source_file_hash=snapshot.source_file_hash,
        source_file_size_bytes=snapshot.source_file_size_bytes,
        local_storage_key_fingerprint=snapshot.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=snapshot.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=snapshot.candidate_storage_key_fingerprint,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        route_version_at_prepare=snapshot.route_version_at_prepare,
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


def activate_recovery_durable_read_promotion_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryDurableReadPromotionReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRoutingConflict(
            "Durable read routing activation reason is required"
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
            and route.route_authority_kind == "durable_promotion"
            and route.active_lease_id is None
            and route.active_durable_lease_id == lease.id
            and route.active_replica_id == lease.replica_id
            and route.read_path_switched is True
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Durable read routing activation replay does not match active authority"
            )
        return lease, route, None, "unchanged"
    if lease.status != "prepared":
        raise RecoveryDurableReadRoutingConflict(
            "Only a prepared durable read routing lease can be activated"
        )
    if lease.prepared_by_id == activated_by_id:
        raise RecoveryDurableReadRoutingConflict(
            "Durable read routing activation requires a different Admin from the preparer"
        )
    if lease.authorization_approved_by_id == activated_by_id:
        raise RecoveryDurableReadRoutingConflict(
            "Durable read routing activator must differ from the Phase L approver"
        )
    if current_time >= _as_utc(lease.activation_expires_at):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=activated_by_id,
            reason="Durable read routing activation window expired",
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
    except (RecoveryDurableReadRoutingConflict, RecoveryDurableReadRoutingNotFound) as exc:
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh durable read routing preflight failed: {type(exc).__name__}",
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
            reason="Durable read routing lineage or route drifted before activation",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"

    lease.status = "activated"
    lease.activated_by_id = activated_by_id
    lease.activated_at = current_time
    lease.activation_reason = normalized_reason
    lease.route_expires_at = current_time + DURABLE_READ_ROUTE_WINDOW
    lease.routable_authority_created = True
    lease.durable_read_route_created = True
    lease.read_path_switched = True

    route.route_class = "recovery_replica"
    route.route_authority_kind = "durable_promotion"
    route.active_lease_id = None
    route.active_durable_lease_id = lease.id
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
        route_authority_kind="durable_promotion",
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
    lease: EvidenceRecoveryDurableReadPromotionLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadPromotionReceipt:
    if not (
        route.route_class == "recovery_replica"
        and route.route_authority_kind == "durable_promotion"
        and route.active_lease_id is None
        and route.active_durable_lease_id == lease.id
        and route.active_replica_id == lease.replica_id
        and route.read_path_switched is True
    ):
        raise RecoveryDurableReadRoutingConflict(
            "Active read route does not match the durable lease being restored"
        )
    route.route_class = "local_source"
    route.route_authority_kind = "local"
    route.active_lease_id = None
    route.active_durable_lease_id = None
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


def rollback_recovery_durable_read_promotion_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryDurableReadPromotionReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRoutingConflict(
            "Durable read routing rollback reason is required"
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
            raise RecoveryDurableReadRoutingConflict(
                "Durable read rollback replay does not match the original rollback"
            )
        return lease, route, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryDurableReadRoutingConflict(
            "Only an activated durable read routing lease can be rolled back"
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


def _validate_active_durable_read(
    db: Session,
    *,
    document: Document,
    route: EvidenceRecoveryReadPathRoute,
    lease: EvidenceRecoveryDurableReadPromotionLease,
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
        and route.route_authority_kind == "durable_promotion"
        and route.active_lease_id is None
        and route.active_durable_lease_id == lease.id
        and route.active_replica_id == lease.replica_id
        and route.route_version == lease.route_version_at_prepare + 1
        and route.read_path_switched is True
        and _route_matches_lease(route, lease)
    ):
        raise RecoveryDurableReadRoutingConflict(
            "Active durable recovery read route is structurally inconsistent"
        )
    if now >= _as_utc(lease.route_expires_at):
        raise RecoveryDurableReadRoutingConflict(
            "Active durable recovery read route expired; reconciliation or rollback is required"
        )

    try:
        authorization = _get_authorization(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            authorization_id=lease.authorization_id,
        )
        if not (
            authorization.status == "approved"
            and authorization.approved_by_id == lease.authorization_approved_by_id
            and authorization.authorization_hash == lease.authorization_hash
            and authorization.request_snapshot_hash
            == lease.authorization_request_snapshot_hash
            and authorization.integrity_proof_hash
            == lease.authorization_integrity_proof_hash
            and authorization.qualification_id == lease.qualification_id
            and authorization.replica_id == lease.replica_id
            and authorization.qualification_hash == lease.qualification_hash
            and authorization.qualification_bundle_hash == lease.qualification_bundle_hash
            and authorization.replica_hash == lease.replica_hash
            and authorization.source_file_hash == lease.source_file_hash
            and authorization.source_file_size_bytes == lease.source_file_size_bytes
            and authorization.local_storage_key_fingerprint
            == lease.local_storage_key_fingerprint
            and authorization.recovery_bucket_fingerprint
            == lease.recovery_bucket_fingerprint
            and authorization.candidate_storage_key_fingerprint
            == lease.candidate_storage_key_fingerprint
            and authorization.source_authority_fingerprint
            == lease.source_authority_fingerprint
            and authorization.candidate_authority_fingerprint
            == lease.candidate_authority_fingerprint
            and authorization.configuration_fingerprint == lease.configuration_fingerprint
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Phase L authorization lineage drifted after durable activation"
            )
        approval = _approval_receipt(db, authorization=authorization)
        if (
            approval.id != lease.authorization_approval_receipt_id
            or approval.receipt_hash != lease.authorization_approval_receipt_hash
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Phase L approval receipt drifted after durable activation"
            )
        qualification = _get_qualification(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            qualification_id=lease.qualification_id,
        )
        if not (
            qualification.status == "qualified"
            and qualification.qualification_hash == lease.qualification_hash
            and qualification.qualification_bundle_hash == lease.qualification_bundle_hash
            and qualification.replica_id == lease.replica_id
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Phase K qualification lineage drifted after durable activation"
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
            raise RecoveryDurableReadRoutingConflict(
                "Local or recovery replica lineage drifted after durable activation"
            )
        candidate_payload = _read_verified_candidate(replica)
        if (
            hashlib.sha256(candidate_payload).hexdigest() != lease.source_file_hash
            or len(candidate_payload) != lease.source_file_size_bytes
        ):
            raise RecoveryDurableReadRoutingConflict(
                "Durable recovery candidate bytes failed fresh integrity verification"
            )
        return candidate_payload
    except RecoveryDurableReadRoutingError:
        raise
    except RecoveryDurableReadPromotionAuthorizationNotFound as exc:
        raise RecoveryDurableReadRoutingNotFound(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryDurableReadRoutingNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict) as exc:
        raise RecoveryDurableReadRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadRoutingUnavailable(str(exc)) from exc


def reconcile_recovery_durable_read_promotion_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    reconciled_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryDurableReadPromotionReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRoutingConflict(
            "Durable read routing reconciliation reason is required"
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
        raise RecoveryDurableReadRoutingConflict(
            "Only an activated durable read routing lease can be reconciled"
        )
    if current_time >= _as_utc(lease.route_expires_at):
        receipt = _restore_local_route(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=reconciled_by_id,
            reason="Durable read routing operational window expired and was reconciled to local source",
            now=current_time,
        )
        return lease, route, receipt, "expired"

    document = _load_document(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    _validate_active_durable_read(
        db,
        document=document,
        route=route,
        lease=lease,
        now=current_time,
    )
    return lease, route, None, "unchanged"


def resolve_recovery_document_read(
    db: Session,
    *,
    document: Document,
    now: datetime | None = None,
) -> tuple[bytes | None, str]:
    route = _get_route(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        required=False,
    )
    if route is None or route.route_authority_kind in {"local", "temporary_cutover"}:
        try:
            return resolve_temporary_recovery_document_read(db, document=document, now=now)
        except RecoveryRoutableReadCutoverNotFound as exc:
            raise RecoveryDurableReadRoutingNotFound(str(exc)) from exc
        except RecoveryRoutableReadCutoverConflict as exc:
            raise RecoveryDurableReadRoutingConflict(str(exc)) from exc
        except RecoveryRoutableReadCutoverUnavailable as exc:
            raise RecoveryDurableReadRoutingUnavailable(str(exc)) from exc
    if route.route_authority_kind != "durable_promotion":
        raise RecoveryDurableReadRoutingConflict(
            "Read route contains an unknown authority kind"
        )
    if route.active_durable_lease_id is None:
        raise RecoveryDurableReadRoutingConflict(
            "Durable recovery route has no active durable lease"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        lease_id=route.active_durable_lease_id,
    )
    payload = _validate_active_durable_read(
        db,
        document=document,
        route=route,
        lease=lease,
        now=current_time,
    )
    return payload, "recovery-replica-durable"


def get_recovery_durable_read_promotion_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryDurableReadPromotionLease:
    return _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )


def list_recovery_durable_read_promotion_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> list[EvidenceRecoveryDurableReadPromotionReceipt]:
    _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadPromotionReceipt)
            .where(
                EvidenceRecoveryDurableReadPromotionReceipt.organization_id
                == organization_id,
                EvidenceRecoveryDurableReadPromotionReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadPromotionReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadPromotionReceipt.durable_lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadPromotionReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadPromotionReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadPromotionReceipt.id.asc(),
            )
        ).all()
    )
