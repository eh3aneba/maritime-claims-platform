from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.object_storage import ObjectStorageError, ObjectStorageIntegrityError, ObjectStorageNotFound
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable, _build_store
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import EvidenceRecoveryRoutableDualWriteCanaryRoute
from app.modules.documents.recovery_write_ownership_transition_authorization_models import EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt
from app.modules.documents.recovery_write_ownership_transition_authorization_service import (
    RecoveryWriteOwnershipTransitionAuthorizationConflict,
    RecoveryWriteOwnershipTransitionAuthorizationNotFound,
    RecoveryWriteOwnershipTransitionAuthorizationUnavailable,
    _fresh_ac,
    _matches_authorization,
    get_recovery_write_ownership_transition_authorization,
)
from app.modules.documents.recovery_write_ownership_transition_execution_models import (
    EvidenceRecoveryWriteOwnershipTransitionLease,
    EvidenceRecoveryWriteOwnershipTransitionReceipt,
)


WRITE_OWNERSHIP_TRANSITION_WINDOW = timedelta(minutes=10)


class RecoveryWriteOwnershipTransitionExecutionError(RuntimeError):
    pass


class RecoveryWriteOwnershipTransitionExecutionNotFound(RecoveryWriteOwnershipTransitionExecutionError):
    pass


class RecoveryWriteOwnershipTransitionExecutionConflict(RecoveryWriteOwnershipTransitionExecutionError):
    pass


class RecoveryWriteOwnershipTransitionExecutionUnavailable(RecoveryWriteOwnershipTransitionExecutionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approved_receipt(db: Session, *, authorization) -> EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt).where(
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.organization_id == authorization.organization_id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.claim_id == authorization.claim_id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.document_id == authorization.document_id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.authorization_id == authorization.id,
                EvidenceRecoveryWriteOwnershipTransitionAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AE requires exactly one Phase AD approved receipt")
    receipt = receipts[0]
    if not all(
        (
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            receipt.actor_id == authorization.approved_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
            receipt.health_state == "healthy",
            receipt.phase_ac_health_qualification_id == authorization.phase_ac_health_qualification_id,
            receipt.phase_ac_health_qualification_hash == authorization.phase_ac_health_qualification_hash,
            receipt.phase_ac_health_receipt_hash == authorization.phase_ac_health_receipt_hash,
            receipt.request_snapshot_hash == authorization.request_snapshot_hash,
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.local_authoritative is True,
            receipt.storage_write_performed is False,
            receipt.write_route_lease_created is False,
            receipt.routable_dual_write_active is False,
            receipt.durable_write_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_put_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AD approved receipt lineage is inconsistent")
    return receipt


def _validate_approved_authorization(authorization, *, current: datetime) -> None:
    if not all(
        (
            authorization.status == "approved",
            authorization.health_state == "healthy",
            authorization.max_transition_windows == 1,
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.authorization_expires_at is not None,
            current < _as_utc(authorization.authorization_expires_at),
            authorization.local_authoritative is True,
            authorization.storage_write_performed is False,
            authorization.write_route_lease_created is False,
            authorization.routable_dual_write_active is False,
            authorization.durable_write_authority_created is False,
            authorization.read_path_switched is False,
            authorization.write_path_switched is False,
            authorization.document_storage_key_mutated is False,
            authorization.authoritative_storage_changed is False,
            authorization.destructive_action_performed is False,
            authorization.s3_put_performed is False,
            authorization.s3_copy_performed is False,
            authorization.s3_delete_performed is False,
            authorization.local_delete_performed is False,
        )
    ):
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Phase AE requires one exact approved, healthy, unexpired Phase AD authorization"
        )


def _fresh_authorization_snapshot(db: Session, *, authorization):
    try:
        q, ac_receipt, snapshot = _fresh_ac(
            db,
            organization_id=authorization.organization_id,
            claim_id=authorization.claim_id,
            document_id=authorization.document_id,
            health_qualification_id=authorization.phase_ac_health_qualification_id,
        )
    except RecoveryWriteOwnershipTransitionAuthorizationUnavailable as exc:
        raise RecoveryWriteOwnershipTransitionExecutionUnavailable(str(exc)) from exc
    except RecoveryWriteOwnershipTransitionAuthorizationNotFound as exc:
        raise RecoveryWriteOwnershipTransitionExecutionNotFound(str(exc)) from exc
    except RecoveryWriteOwnershipTransitionAuthorizationConflict as exc:
        raise RecoveryWriteOwnershipTransitionExecutionConflict(str(exc)) from exc

    if not _matches_authorization(authorization, q, ac_receipt, snapshot):
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Phase AD authorization snapshot drifted before Phase AE activation"
        )

    write_route = snapshot.write_route
    read_route = snapshot.read_route
    if not all(
        (
            write_route.write_mode == "local_only",
            write_route.active_canary_lease_id is None,
            write_route.active_write_ownership_transition_lease_id is None,
            write_route.route_version == authorization.write_route_version_at_request,
            write_route.local_authoritative is True,
            write_route.durable_write_authority_created is False,
            write_route.read_path_switched is False,
            write_route.write_path_switched is False,
            write_route.document_storage_key_mutated is False,
            write_route.authoritative_storage_changed is False,
            write_route.destructive_action_performed is False,
            write_route.s3_copy_performed is False,
            write_route.s3_delete_performed is False,
            write_route.local_delete_performed is False,
            read_route.route_class == "local_source",
            read_route.route_authority_kind == "local",
            read_route.active_lease_id is None,
            read_route.active_durable_lease_id is None,
            read_route.active_durable_renewal_lease_id is None,
            read_route.active_durable_reauthorized_renewal_lease_id is None,
            read_route.active_read_ownership_transition_lease_id is None,
            read_route.active_replica_id is None,
            read_route.route_version == authorization.read_route_version_at_request,
            read_route.read_path_switched is False,
            read_route.write_path_switched is False,
            read_route.document_storage_key_mutated is False,
            read_route.authoritative_storage_changed is False,
            read_route.destructive_action_performed is False,
        )
    ):
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Phase AE requires exact clean local read/write routing before activation"
        )
    return q, ac_receipt, snapshot


def _verify_recovery_replica_bytes(*, authorization, snapshot):
    replica = snapshot.replica
    candidate_fingerprint = hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
    if not all(
        (
            replica.id == authorization.replica_id,
            replica.replica_hash == authorization.replica_hash,
            replica.source_file_hash == authorization.source_file_hash,
            replica.source_file_size_bytes == authorization.source_file_size_bytes,
            replica.source_storage_key_fingerprint == authorization.local_storage_key_fingerprint,
            replica.recovery_bucket_fingerprint == authorization.recovery_bucket_fingerprint,
            candidate_fingerprint == authorization.candidate_storage_key_fingerprint,
        )
    ):
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Recovery replica lineage drifted before Phase AE activation")
    try:
        store = _build_store()
    except RecoveryReplicationUnavailable as exc:
        raise RecoveryWriteOwnershipTransitionExecutionUnavailable(str(exc)) from exc
    if store.sanitized_health_identity.bucket_fingerprint != authorization.recovery_bucket_fingerprint:
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Recovery storage configuration drifted before Phase AE activation"
        )
    try:
        metadata = store.head_object(storage_key=replica.recovery_storage_key)
        payload = store.get_bytes(storage_key=replica.recovery_storage_key, expected_sha256=authorization.source_file_hash)
    except ObjectStorageNotFound as exc:
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Recovery replica object is missing before Phase AE activation"
        ) from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Recovery replica failed byte-integrity verification before Phase AE activation"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryWriteOwnershipTransitionExecutionUnavailable(
            "Recovery replica verification is temporarily unavailable"
        ) from exc

    observed_hash = hashlib.sha256(payload).hexdigest()
    observed_size = len(payload)
    if not all(
        (
            metadata.file_hash == authorization.source_file_hash,
            metadata.file_size_bytes == authorization.source_file_size_bytes,
            observed_hash == authorization.source_file_hash,
            observed_size == authorization.source_file_size_bytes,
        )
    ):
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Recovery replica bytes or metadata drifted before Phase AE activation"
        )
    return observed_hash, observed_size, metadata.etag


def _activation_snapshot_hash(
    authorization,
    approval_receipt,
    q,
    ac_receipt,
    snapshot,
    *,
    observed_hash: str,
    observed_size: int,
    observed_etag: str | None,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_request_snapshot_hash": authorization.request_snapshot_hash,
            "authorization_approval_receipt_id": str(approval_receipt.id),
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "phase_ac_health_qualification_id": str(q.id),
            "phase_ac_health_qualification_hash": q.health_qualification_hash,
            "phase_ac_health_receipt_hash": ac_receipt.receipt_hash,
            "canary_lease_id": str(snapshot.lease.id),
            "canary_lease_hash": snapshot.lease.lease_hash,
            "replica_id": str(snapshot.replica.id),
            "replica_hash": snapshot.replica.replica_hash,
            "source_file_hash": authorization.source_file_hash,
            "source_file_size_bytes": authorization.source_file_size_bytes,
            "local_storage_key_fingerprint": authorization.local_storage_key_fingerprint,
            "candidate_storage_key_fingerprint": authorization.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": authorization.source_authority_fingerprint,
            "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
            "configuration_fingerprint": authorization.configuration_fingerprint,
            "observed_replica_hash": observed_hash,
            "observed_replica_size_bytes": observed_size,
            "observed_replica_etag": observed_etag,
            "read_route_version_at_activation": snapshot.read_route.route_version,
            "write_route_version_before_activation": snapshot.write_route.route_version,
            "write_mode": snapshot.write_route.write_mode,
            "active_canary_lease_id": None,
            "active_write_ownership_transition_lease_id": None,
            "local_authoritative": True,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
        }
    )


def _lease_hash(
    *,
    authorization,
    approval_receipt,
    activation_snapshot_hash: str,
    observed_hash: str,
    observed_size: int,
    activated_by_id: UUID,
    activated_at: datetime,
    route_expires_at: datetime,
    reason: str,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "activation_snapshot_hash": activation_snapshot_hash,
            "observed_replica_hash": observed_hash,
            "observed_replica_size_bytes": observed_size,
            "activated_by_id": str(activated_by_id),
            "activated_at": _utc_iso(activated_at),
            "route_expires_at": _utc_iso(route_expires_at),
            "activation_reason": reason,
            "local_authoritative": True,
            "bounded_write_ownership_transition_active": True,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": True,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )


def _receipt_hash(
    lease,
    *,
    phase: str,
    from_write_mode: str,
    to_write_mode: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> str:
    active = phase == "activated"
    return _canonical_hash(
        {
            "transition_lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "phase": phase,
            "from_write_mode": from_write_mode,
            "to_write_mode": to_write_mode,
            "route_version": route_version,
            "authorization_hash": lease.authorization_hash,
            "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
            "phase_ac_health_qualification_hash": lease.phase_ac_health_qualification_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "observed_replica_hash": lease.observed_replica_hash,
            "observed_replica_size_bytes": lease.observed_replica_size_bytes,
            "activation_snapshot_hash": lease.activation_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "bounded_write_ownership_transition_active": active,
            "local_authoritative": True,
            "storage_write_performed": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": active,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_put_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_overwrite_performed": False,
            "local_move_performed": False,
            "local_delete_performed": False,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
        }
    )


def _add_receipt(
    db: Session,
    lease,
    *,
    phase: str,
    from_write_mode: str,
    to_write_mode: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    now: datetime,
):
    active = phase == "activated"
    receipt = EvidenceRecoveryWriteOwnershipTransitionReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        transition_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        phase=phase,
        from_write_mode=from_write_mode,
        to_write_mode=to_write_mode,
        route_version=route_version,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        phase_ac_health_qualification_hash=lease.phase_ac_health_qualification_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        observed_replica_hash=lease.observed_replica_hash,
        observed_replica_size_bytes=lease.observed_replica_size_bytes,
        activation_snapshot_hash=lease.activation_snapshot_hash,
        lease_hash=lease.lease_hash,
        receipt_hash=_receipt_hash(
            lease,
            phase=phase,
            from_write_mode=from_write_mode,
            to_write_mode=to_write_mode,
            route_version=route_version,
            actor_id=actor_id,
            reason=reason,
            transitioned_at=now,
        ),
        bounded_write_ownership_transition_active=active,
        local_authoritative=True,
        storage_write_performed=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=active,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _activation_receipt(db: Session, *, lease):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryWriteOwnershipTransitionReceipt).where(
                EvidenceRecoveryWriteOwnershipTransitionReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.transition_lease_id == lease.id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.phase == "activated",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AE lease must have exactly one activation receipt")
    return receipts[0]


def get_recovery_write_ownership_transition_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryWriteOwnershipTransitionLease).where(
        EvidenceRecoveryWriteOwnershipTransitionLease.id == lease_id,
        EvidenceRecoveryWriteOwnershipTransitionLease.organization_id == organization_id,
        EvidenceRecoveryWriteOwnershipTransitionLease.claim_id == claim_id,
        EvidenceRecoveryWriteOwnershipTransitionLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryWriteOwnershipTransitionExecutionNotFound("Phase AE write-ownership transition lease not found")
    return lease


def _load_write_route(db: Session, *, lease, for_update: bool = True):
    stmt = select(EvidenceRecoveryRoutableDualWriteCanaryRoute).where(
        EvidenceRecoveryRoutableDualWriteCanaryRoute.organization_id == lease.organization_id,
        EvidenceRecoveryRoutableDualWriteCanaryRoute.claim_id == lease.claim_id,
        EvidenceRecoveryRoutableDualWriteCanaryRoute.document_id == lease.document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    route = db.scalar(stmt)
    if route is None:
        raise RecoveryWriteOwnershipTransitionExecutionNotFound("Dedicated write route not found")
    return route


def activate_recovery_write_ownership_transition(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AE activation reason is required")
    current = _as_utc(now or _utc_now())
    authorization = get_recovery_write_ownership_transition_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )

    existing = db.scalar(
        select(EvidenceRecoveryWriteOwnershipTransitionLease)
        .where(
            EvidenceRecoveryWriteOwnershipTransitionLease.organization_id == organization_id,
            EvidenceRecoveryWriteOwnershipTransitionLease.claim_id == claim_id,
            EvidenceRecoveryWriteOwnershipTransitionLease.document_id == document_id,
            EvidenceRecoveryWriteOwnershipTransitionLease.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.activated_by_id == activated_by_id and existing.activation_reason == normalized_reason:
            return existing, _activation_receipt(db, lease=existing), "unchanged"
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Phase AD authorization has already been consumed by a Phase AE lease"
        )

    _validate_approved_authorization(authorization, current=current)
    approval_receipt = _approved_receipt(db, authorization=authorization)

    forbidden_actors = {
        authorization.requested_by_id,
        authorization.approved_by_id,
        authorization.phase_ac_qualified_by_id,
        authorization.phase_ab_activated_by_id,
        authorization.phase_aa_requested_by_id,
        authorization.phase_aa_approved_by_id,
        authorization.phase_z_qualified_by_id,
        authorization.phase_y_executed_by_id,
        authorization.phase_x_approved_by_id,
    }
    if activated_by_id in forbidden_actors:
        raise RecoveryWriteOwnershipTransitionExecutionConflict(
            "Phase AE activator must be independent from Phase AD and upstream governance actors"
        )

    q, ac_receipt, snapshot = _fresh_authorization_snapshot(db, authorization=authorization)
    observed_hash, observed_size, observed_etag = _verify_recovery_replica_bytes(
        authorization=authorization,
        snapshot=snapshot,
    )
    activation_snapshot_hash = _activation_snapshot_hash(
        authorization,
        approval_receipt,
        q,
        ac_receipt,
        snapshot,
        observed_hash=observed_hash,
        observed_size=observed_size,
        observed_etag=observed_etag,
    )
    route_expires_at = current + WRITE_OWNERSHIP_TRANSITION_WINDOW
    before_version = snapshot.write_route.route_version
    after_version = before_version + 1
    lease_hash = _lease_hash(
        authorization=authorization,
        approval_receipt=approval_receipt,
        activation_snapshot_hash=activation_snapshot_hash,
        observed_hash=observed_hash,
        observed_size=observed_size,
        activated_by_id=activated_by_id,
        activated_at=current,
        route_expires_at=route_expires_at,
        reason=normalized_reason,
    )

    lease = EvidenceRecoveryWriteOwnershipTransitionLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization.id,
        authorization_approval_receipt_id=approval_receipt.id,
        phase_ac_health_qualification_id=authorization.phase_ac_health_qualification_id,
        canary_lease_id=authorization.canary_lease_id,
        replica_id=authorization.replica_id,
        authorization_hash=authorization.authorization_hash,
        authorization_request_snapshot_hash=authorization.request_snapshot_hash,
        authorization_approval_receipt_hash=approval_receipt.receipt_hash,
        phase_ac_health_qualification_hash=authorization.phase_ac_health_qualification_hash,
        phase_ac_health_receipt_hash=authorization.phase_ac_health_receipt_hash,
        canary_lease_hash=authorization.lease_hash,
        replica_hash=authorization.replica_hash,
        source_file_hash=authorization.source_file_hash,
        source_file_size_bytes=authorization.source_file_size_bytes,
        local_storage_key_fingerprint=authorization.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=authorization.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=authorization.candidate_storage_key_fingerprint,
        source_authority_fingerprint=authorization.source_authority_fingerprint,
        candidate_authority_fingerprint=authorization.candidate_authority_fingerprint,
        configuration_fingerprint=authorization.configuration_fingerprint,
        observed_replica_hash=observed_hash,
        observed_replica_size_bytes=observed_size,
        observed_replica_etag=observed_etag,
        read_route_version_at_activation=snapshot.read_route.route_version,
        write_route_version_before_activation=before_version,
        write_route_version_after_activation=after_version,
        activation_snapshot_hash=activation_snapshot_hash,
        lease_hash=lease_hash,
        status="active",
        bounded_write_ownership_transition_active=True,
        write_path_switched=True,
        activated_by_id=activated_by_id,
        activated_at=current,
        route_expires_at=route_expires_at,
        activation_reason=normalized_reason,
        local_authoritative=True,
        storage_write_performed=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(lease)
    db.flush()

    route = snapshot.write_route
    route.write_mode = "recovery_primary"
    route.active_canary_lease_id = None
    route.active_write_ownership_transition_lease_id = lease.id
    route.route_version = after_version
    route.changed_by_id = activated_by_id
    route.changed_at = current
    route.local_authoritative = True
    route.durable_write_authority_created = False
    route.rehearsal_object_routable = False
    route.read_path_switched = False
    route.write_path_switched = True
    route.document_storage_key_mutated = False
    route.authoritative_storage_changed = False
    route.destructive_action_performed = False
    route.s3_copy_performed = False
    route.s3_delete_performed = False
    route.local_delete_performed = False
    db.flush()

    receipt = _add_receipt(
        db,
        lease,
        phase="activated",
        from_write_mode="local_only",
        to_write_mode="recovery_primary",
        route_version=after_version,
        actor_id=activated_by_id,
        reason=normalized_reason,
        now=current,
    )
    return lease, receipt, "activated"


def _route_is_exact_active(route, lease) -> bool:
    return all(
        (
            route.write_mode == "recovery_primary",
            route.active_canary_lease_id is None,
            route.active_write_ownership_transition_lease_id == lease.id,
            route.route_version == lease.write_route_version_after_activation,
            route.local_authoritative is True,
            route.durable_write_authority_created is False,
            route.rehearsal_object_routable is False,
            route.read_path_switched is False,
            route.write_path_switched is True,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.s3_copy_performed is False,
            route.s3_delete_performed is False,
            route.local_delete_performed is False,
        )
    )


def _route_is_safe_local(route) -> bool:
    return all(
        (
            route.write_mode == "local_only",
            route.active_canary_lease_id is None,
            route.active_write_ownership_transition_lease_id is None,
            route.local_authoritative is True,
            route.durable_write_authority_created is False,
            route.rehearsal_object_routable is False,
            route.read_path_switched is False,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.s3_copy_performed is False,
            route.s3_delete_performed is False,
            route.local_delete_performed is False,
        )
    )


def _terminal_receipt(db: Session, *, lease):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryWriteOwnershipTransitionReceipt)
            .where(
                EvidenceRecoveryWriteOwnershipTransitionReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.transition_lease_id == lease.id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.phase.in_(("rolled_back", "expired", "invalidated")),
            )
            .order_by(EvidenceRecoveryWriteOwnershipTransitionReceipt.transitioned_at.asc())
        ).all()
    )
    if len(receipts) > 1:
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AE lease has inconsistent terminal receipts")
    return receipts[0] if receipts else None


def _terminalize(
    db: Session,
    lease,
    route,
    *,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
    restore_route: bool,
):
    from_mode = route.write_mode
    if restore_route:
        if not _route_is_exact_active(route, lease):
            raise RecoveryWriteOwnershipTransitionExecutionConflict(
                "Phase AE active write route drifted; refusing unsafe rollback"
            )
        route.write_mode = "local_only"
        route.active_canary_lease_id = None
        route.active_write_ownership_transition_lease_id = None
        route.route_version += 1
        route.changed_by_id = actor_id
        route.changed_at = now
        route.local_authoritative = True
        route.durable_write_authority_created = False
        route.rehearsal_object_routable = False
        route.read_path_switched = False
        route.write_path_switched = False
        route.document_storage_key_mutated = False
        route.authoritative_storage_changed = False
        route.destructive_action_performed = False
        route.s3_copy_performed = False
        route.s3_delete_performed = False
        route.local_delete_performed = False
        db.flush()

    lease.status = phase
    lease.bounded_write_ownership_transition_active = False
    lease.write_path_switched = False
    lease.terminal_by_id = actor_id
    lease.terminal_at = now
    lease.terminal_reason = reason
    db.flush()

    return _add_receipt(
        db,
        lease,
        phase=phase,
        from_write_mode=from_mode,
        to_write_mode="local_only",
        route_version=route.route_version,
        actor_id=actor_id,
        reason=reason,
        now=now,
    )


def rollback_recovery_write_ownership_transition(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AE rollback reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_recovery_write_ownership_transition_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status != "active":
        receipt = _terminal_receipt(db, lease=lease)
        if lease.status == "rolled_back" and lease.terminal_by_id == rolled_back_by_id and lease.terminal_reason == normalized_reason:
            return lease, receipt, "unchanged"
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Only an active Phase AE lease can be rolled back")
    route = _load_write_route(db, lease=lease)
    receipt = _terminalize(
        db,
        lease,
        route,
        phase="rolled_back",
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        now=current,
        restore_route=True,
    )
    return lease, receipt, "rolled_back"


def reconcile_recovery_write_ownership_transition(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    actor_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryWriteOwnershipTransitionExecutionConflict("Phase AE reconciliation reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_recovery_write_ownership_transition_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status != "active":
        return lease, _terminal_receipt(db, lease=lease), "unchanged"
    if current < _as_utc(lease.route_expires_at):
        return lease, None, "unchanged"

    route = _load_write_route(db, lease=lease)
    if _route_is_exact_active(route, lease):
        receipt = _terminalize(
            db,
            lease,
            route,
            phase="expired",
            actor_id=actor_id,
            reason=normalized_reason,
            now=current,
            restore_route=True,
        )
        return lease, receipt, "expired"
    if _route_is_safe_local(route):
        receipt = _terminalize(
            db,
            lease,
            route,
            phase="invalidated",
            actor_id=actor_id,
            reason=normalized_reason,
            now=current,
            restore_route=False,
        )
        return lease, receipt, "invalidated"
    raise RecoveryWriteOwnershipTransitionExecutionConflict(
        "Phase AE route drift is unsafe; manual recovery is required"
    )


def list_recovery_write_ownership_transition_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
):
    get_recovery_write_ownership_transition_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryWriteOwnershipTransitionReceipt)
            .where(
                EvidenceRecoveryWriteOwnershipTransitionReceipt.organization_id == organization_id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.claim_id == claim_id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.document_id == document_id,
                EvidenceRecoveryWriteOwnershipTransitionReceipt.transition_lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryWriteOwnershipTransitionReceipt.transitioned_at.asc(),
                EvidenceRecoveryWriteOwnershipTransitionReceipt.id.asc(),
            )
        ).all()
    )
