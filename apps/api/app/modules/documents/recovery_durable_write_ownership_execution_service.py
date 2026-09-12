from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_write_ownership_authorization_models import (
    EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt,
)
from app.modules.documents.recovery_durable_write_ownership_authorization_service import (
    RecoveryDurableWriteOwnershipAuthorizationConflict,
    RecoveryDurableWriteOwnershipAuthorizationNotFound,
    RecoveryDurableWriteOwnershipAuthorizationUnavailable,
    _fresh_af,
    _matches_authorization,
    get_durable_write_ownership_authorization,
)
from app.modules.documents.recovery_durable_write_ownership_execution_models import (
    EvidenceRecoveryDurableWriteOwnershipLease,
    EvidenceRecoveryDurableWriteOwnershipReceipt,
    EvidenceRecoveryDurableWriteOwnershipRoute,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


class RecoveryDurableWriteOwnershipExecutionError(RuntimeError):
    pass


class RecoveryDurableWriteOwnershipExecutionNotFound(RecoveryDurableWriteOwnershipExecutionError):
    pass


class RecoveryDurableWriteOwnershipExecutionConflict(RecoveryDurableWriteOwnershipExecutionError):
    pass


class RecoveryDurableWriteOwnershipExecutionUnavailable(RecoveryDurableWriteOwnershipExecutionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approved_ag_receipt(db: Session, *, authorization):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt).where(
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.organization_id == authorization.organization_id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.claim_id == authorization.claim_id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.document_id == authorization.document_id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.authorization_id == authorization.id,
                EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH requires exactly one Phase AG approved receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            receipt.actor_id == authorization.approved_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
            receipt.health_state == "healthy",
            receipt.phase_af_health_qualification_id == authorization.phase_af_health_qualification_id,
            receipt.phase_af_health_qualification_hash == authorization.phase_af_health_qualification_hash,
            receipt.phase_af_health_receipt_hash == authorization.phase_af_health_receipt_hash,
            receipt.request_snapshot_hash == authorization.request_snapshot_hash,
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.local_authoritative is True,
            receipt.storage_write_performed is False,
            receipt.write_route_lease_created is False,
            receipt.write_route_reactivated is False,
            receipt.durable_write_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_put_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_overwrite_performed is False,
            receipt.local_move_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AG approved receipt lineage is inconsistent"
        )
    return receipt


def _validate_approved_authorization(authorization, *, current: datetime) -> None:
    if not all(
        (
            authorization.status == "approved",
            authorization.health_state == "healthy",
            authorization.max_execution_windows == 1,
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.authorization_expires_at is not None,
            current < _as_utc(authorization.authorization_expires_at),
            authorization.local_authoritative is True,
            authorization.storage_write_performed is False,
            authorization.write_route_lease_created is False,
            authorization.write_route_reactivated is False,
            authorization.durable_write_authority_created is False,
            authorization.read_path_switched is False,
            authorization.write_path_switched is False,
            authorization.document_storage_key_mutated is False,
            authorization.authoritative_storage_changed is False,
            authorization.destructive_action_performed is False,
            authorization.s3_put_performed is False,
            authorization.s3_copy_performed is False,
            authorization.s3_delete_performed is False,
            authorization.local_overwrite_performed is False,
            authorization.local_move_performed is False,
            authorization.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH requires one exact approved, healthy, unexpired Phase AG authorization"
        )


def _fresh_authorization_snapshot(db: Session, *, authorization):
    try:
        q, af_receipt, snapshot = _fresh_af(
            db,
            organization_id=authorization.organization_id,
            claim_id=authorization.claim_id,
            document_id=authorization.document_id,
            health_qualification_id=authorization.phase_af_health_qualification_id,
        )
    except RecoveryDurableWriteOwnershipAuthorizationUnavailable as exc:
        raise RecoveryDurableWriteOwnershipExecutionUnavailable(str(exc)) from exc
    except RecoveryDurableWriteOwnershipAuthorizationNotFound as exc:
        raise RecoveryDurableWriteOwnershipExecutionNotFound(str(exc)) from exc
    except RecoveryDurableWriteOwnershipAuthorizationConflict as exc:
        raise RecoveryDurableWriteOwnershipExecutionConflict(str(exc)) from exc

    if not _matches_authorization(authorization, q, af_receipt, snapshot):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AG authorization snapshot drifted before Phase AH activation"
        )
    if not all(
        (
            snapshot.read_route.route_class == "local_source",
            snapshot.read_route.route_authority_kind == "local",
            snapshot.read_route.active_lease_id is None,
            snapshot.read_route.active_durable_lease_id is None,
            snapshot.read_route.active_durable_renewal_lease_id is None,
            snapshot.read_route.active_durable_reauthorized_renewal_lease_id is None,
            snapshot.read_route.active_read_ownership_transition_lease_id is None,
            snapshot.read_route.active_replica_id is None,
            snapshot.read_route.route_version == authorization.read_route_version_at_request,
            snapshot.read_route.read_path_switched is False,
            snapshot.read_route.write_path_switched is False,
            snapshot.read_route.document_storage_key_mutated is False,
            snapshot.read_route.authoritative_storage_changed is False,
            snapshot.read_route.destructive_action_performed is False,
            snapshot.write_route.write_mode == "local_only",
            snapshot.write_route.active_canary_lease_id is None,
            snapshot.write_route.active_write_ownership_transition_lease_id is None,
            snapshot.write_route.route_version == authorization.write_route_version_at_request,
            snapshot.write_route.local_authoritative is True,
            snapshot.write_route.durable_write_authority_created is False,
            snapshot.write_route.read_path_switched is False,
            snapshot.write_route.write_path_switched is False,
            snapshot.write_route.document_storage_key_mutated is False,
            snapshot.write_route.authoritative_storage_changed is False,
            snapshot.write_route.destructive_action_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH requires exact clean local read and experimental-write routing before activation"
        )
    return q, af_receipt, snapshot


def _load_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryDurableWriteOwnershipRoute).where(
        EvidenceRecoveryDurableWriteOwnershipRoute.organization_id == organization_id,
        EvidenceRecoveryDurableWriteOwnershipRoute.claim_id == claim_id,
        EvidenceRecoveryDurableWriteOwnershipRoute.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _route_is_safe_local(route) -> bool:
    return all(
        (
            route.write_mode == "local_only",
            route.active_durable_write_ownership_lease_id is None,
            route.local_authoritative is True,
            route.storage_write_performed is False,
            route.durable_write_authority_created is False,
            route.read_path_switched is False,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.s3_put_performed is False,
            route.s3_copy_performed is False,
            route.s3_delete_performed is False,
            route.local_overwrite_performed is False,
            route.local_move_performed is False,
            route.local_delete_performed is False,
        )
    )


def _route_is_exact_active(route, lease) -> bool:
    return all(
        (
            route.write_mode == "recovery_primary",
            route.active_durable_write_ownership_lease_id == lease.id,
            route.route_version == lease.durable_route_version_after_activation,
            route.local_authoritative is True,
            route.storage_write_performed is False,
            route.durable_write_authority_created is True,
            route.read_path_switched is False,
            route.write_path_switched is True,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.s3_put_performed is False,
            route.s3_copy_performed is False,
            route.s3_delete_performed is False,
            route.local_overwrite_performed is False,
            route.local_move_performed is False,
            route.local_delete_performed is False,
        )
    )


def _activation_snapshot_hash(authorization, approval_receipt, q, af_receipt, snapshot, *, durable_route) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_request_snapshot_hash": authorization.request_snapshot_hash,
            "authorization_approval_receipt_id": str(approval_receipt.id),
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "phase_af_health_qualification_id": str(q.id),
            "phase_af_health_qualification_hash": q.health_qualification_hash,
            "phase_af_health_receipt_hash": af_receipt.receipt_hash,
            "transition_lease_id": str(snapshot.lease.id),
            "transition_lease_hash": snapshot.lease.lease_hash,
            "replica_id": str(snapshot.replica.id),
            "replica_hash": snapshot.replica.replica_hash,
            "source_file_hash": authorization.source_file_hash,
            "source_file_size_bytes": authorization.source_file_size_bytes,
            "local_storage_key_fingerprint": authorization.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": authorization.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": authorization.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": authorization.source_authority_fingerprint,
            "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
            "configuration_fingerprint": authorization.configuration_fingerprint,
            "observed_local_hash": snapshot.observed_local_hash,
            "observed_local_size_bytes": snapshot.observed_local_size_bytes,
            "observed_recovery_hash": snapshot.observed_recovery_hash,
            "observed_recovery_size_bytes": snapshot.observed_recovery_size_bytes,
            "observed_recovery_etag": snapshot.observed_recovery_etag,
            "read_route_version_at_activation": snapshot.read_route.route_version,
            "experimental_write_route_version_at_activation": snapshot.write_route.route_version,
            "durable_route_version_before_activation": durable_route.route_version if durable_route else 0,
            "durable_route_mode_before_activation": durable_route.write_mode if durable_route else "local_only",
            "durable_route_active_lease_before_activation": None,
            "local_authoritative": True,
            "storage_write_performed": False,
            "read_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )


def _lease_hash(
    *,
    authorization,
    approval_receipt,
    activation_snapshot_hash: str,
    activated_by_id: UUID,
    activated_at: datetime,
    reason: str,
    before_version: int,
    after_version: int,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "activation_snapshot_hash": activation_snapshot_hash,
            "activated_by_id": str(activated_by_id),
            "activated_at": _utc_iso(activated_at),
            "activation_reason": reason,
            "durable_route_version_before_activation": before_version,
            "durable_route_version_after_activation": after_version,
            "durable_write_ownership_active": True,
            "local_authoritative": True,
            "storage_write_performed": False,
            "durable_write_authority_created": True,
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
            "lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "phase": phase,
            "from_write_mode": from_write_mode,
            "to_write_mode": to_write_mode,
            "route_version": route_version,
            "authorization_hash": lease.authorization_hash,
            "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
            "phase_af_health_qualification_hash": lease.phase_af_health_qualification_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "activation_snapshot_hash": lease.activation_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "durable_write_ownership_active": active,
            "local_authoritative": True,
            "storage_write_performed": False,
            "durable_write_authority_created": active,
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
    receipt = EvidenceRecoveryDurableWriteOwnershipReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        lease_id=lease.id,
        authorization_id=lease.authorization_id,
        phase=phase,
        from_write_mode=from_write_mode,
        to_write_mode=to_write_mode,
        route_version=route_version,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        phase_af_health_qualification_hash=lease.phase_af_health_qualification_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
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
        durable_write_ownership_active=active,
        durable_write_authority_created=active,
        write_path_switched=active,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        storage_write_performed=False,
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
    db.add(receipt)
    db.flush()
    return receipt


def _activation_receipt(db: Session, *, lease):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipReceipt).where(
                EvidenceRecoveryDurableWriteOwnershipReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.lease_id == lease.id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.phase == "activated",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH lease must have exactly one activation receipt"
        )
    return receipts[0]


def _terminal_receipt(db: Session, *, lease):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipReceipt)
            .where(
                EvidenceRecoveryDurableWriteOwnershipReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.lease_id == lease.id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.phase.in_(("rolled_back", "invalidated")),
            )
            .order_by(EvidenceRecoveryDurableWriteOwnershipReceipt.transitioned_at.asc())
        ).all()
    )
    if len(receipts) > 1:
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH lease has inconsistent terminal receipts"
        )
    return receipts[0] if receipts else None


def get_durable_write_ownership_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryDurableWriteOwnershipLease).where(
        EvidenceRecoveryDurableWriteOwnershipLease.id == lease_id,
        EvidenceRecoveryDurableWriteOwnershipLease.organization_id == organization_id,
        EvidenceRecoveryDurableWriteOwnershipLease.claim_id == claim_id,
        EvidenceRecoveryDurableWriteOwnershipLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryDurableWriteOwnershipExecutionNotFound(
            "Phase AH durable write-ownership lease not found"
        )
    return lease


def get_durable_write_ownership_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
):
    route = _load_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    if route is None:
        raise RecoveryDurableWriteOwnershipExecutionNotFound(
            "Phase AH durable write-ownership route not found"
        )
    return route


def activate_durable_write_ownership(
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
        raise RecoveryDurableWriteOwnershipExecutionConflict("Phase AH activation reason is required")
    current = _as_utc(now or _utc_now())
    try:
        authorization = get_durable_write_ownership_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            for_update=True,
        )
    except RecoveryDurableWriteOwnershipAuthorizationNotFound as exc:
        raise RecoveryDurableWriteOwnershipExecutionNotFound(str(exc)) from exc

    existing = db.scalar(
        select(EvidenceRecoveryDurableWriteOwnershipLease)
        .where(
            EvidenceRecoveryDurableWriteOwnershipLease.organization_id == organization_id,
            EvidenceRecoveryDurableWriteOwnershipLease.claim_id == claim_id,
            EvidenceRecoveryDurableWriteOwnershipLease.document_id == document_id,
            EvidenceRecoveryDurableWriteOwnershipLease.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.activated_by_id == activated_by_id and existing.activation_reason == normalized_reason:
            return existing, _activation_receipt(db, lease=existing), "unchanged"
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AG authorization has already been consumed by a Phase AH lease"
        )

    _validate_approved_authorization(authorization, current=current)
    approval_receipt = _approved_ag_receipt(db, authorization=authorization)
    forbidden_actors = {
        authorization.requested_by_id,
        authorization.approved_by_id,
        authorization.phase_af_requested_by_id,
        authorization.phase_af_qualified_by_id,
        authorization.phase_ae_activated_by_id,
        authorization.phase_ad_requested_by_id,
        authorization.phase_ad_approved_by_id,
        authorization.phase_ac_qualified_by_id,
        authorization.phase_ab_activated_by_id,
        authorization.phase_aa_requested_by_id,
        authorization.phase_aa_approved_by_id,
        authorization.phase_z_qualified_by_id,
        authorization.phase_y_executed_by_id,
        authorization.phase_x_approved_by_id,
    }
    if activated_by_id in forbidden_actors:
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH activator must be independent from Phase AG and upstream governance actors"
        )

    q, af_receipt, snapshot = _fresh_authorization_snapshot(db, authorization=authorization)
    durable_route = _load_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    if durable_route is not None and not _route_is_safe_local(durable_route):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH requires an absent or exact local-only durable write route before activation"
        )

    before_version = durable_route.route_version if durable_route is not None else 0
    after_version = before_version + 1
    activation_snapshot_hash = _activation_snapshot_hash(
        authorization,
        approval_receipt,
        q,
        af_receipt,
        snapshot,
        durable_route=durable_route,
    )
    lease_hash = _lease_hash(
        authorization=authorization,
        approval_receipt=approval_receipt,
        activation_snapshot_hash=activation_snapshot_hash,
        activated_by_id=activated_by_id,
        activated_at=current,
        reason=normalized_reason,
        before_version=before_version,
        after_version=after_version,
    )

    lease = EvidenceRecoveryDurableWriteOwnershipLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization.id,
        authorization_approval_receipt_id=approval_receipt.id,
        phase_af_health_qualification_id=authorization.phase_af_health_qualification_id,
        transition_lease_id=authorization.transition_lease_id,
        replica_id=authorization.replica_id,
        authorization_hash=authorization.authorization_hash,
        authorization_request_snapshot_hash=authorization.request_snapshot_hash,
        authorization_approval_receipt_hash=approval_receipt.receipt_hash,
        phase_af_health_qualification_hash=authorization.phase_af_health_qualification_hash,
        phase_af_health_receipt_hash=authorization.phase_af_health_receipt_hash,
        transition_lease_hash=authorization.transition_lease_hash,
        replica_hash=authorization.replica_hash,
        source_file_hash=authorization.source_file_hash,
        source_file_size_bytes=authorization.source_file_size_bytes,
        local_storage_key_fingerprint=authorization.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=authorization.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=authorization.candidate_storage_key_fingerprint,
        source_authority_fingerprint=authorization.source_authority_fingerprint,
        candidate_authority_fingerprint=authorization.candidate_authority_fingerprint,
        configuration_fingerprint=authorization.configuration_fingerprint,
        observed_local_hash=snapshot.observed_local_hash,
        observed_local_size_bytes=snapshot.observed_local_size_bytes,
        observed_recovery_hash=snapshot.observed_recovery_hash,
        observed_recovery_size_bytes=snapshot.observed_recovery_size_bytes,
        observed_recovery_etag=snapshot.observed_recovery_etag,
        read_route_version_at_activation=snapshot.read_route.route_version,
        experimental_write_route_version_at_activation=snapshot.write_route.route_version,
        durable_route_version_before_activation=before_version,
        durable_route_version_after_activation=after_version,
        activation_snapshot_hash=activation_snapshot_hash,
        lease_hash=lease_hash,
        status="active",
        durable_write_ownership_active=True,
        durable_write_authority_created=True,
        write_path_switched=True,
        activated_by_id=activated_by_id,
        activated_at=current,
        activation_reason=normalized_reason,
        local_authoritative=True,
        storage_write_performed=False,
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

    if durable_route is None:
        durable_route = EvidenceRecoveryDurableWriteOwnershipRoute(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            write_mode="recovery_primary",
            active_durable_write_ownership_lease_id=lease.id,
            route_version=after_version,
            durable_write_authority_created=True,
            write_path_switched=True,
            changed_by_id=activated_by_id,
            changed_at=current,
            local_authoritative=True,
            storage_write_performed=False,
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
        db.add(durable_route)
    else:
        durable_route.write_mode = "recovery_primary"
        durable_route.active_durable_write_ownership_lease_id = lease.id
        durable_route.route_version = after_version
        durable_route.durable_write_authority_created = True
        durable_route.write_path_switched = True
        durable_route.changed_by_id = activated_by_id
        durable_route.changed_at = current
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


def rollback_durable_write_ownership(
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
        raise RecoveryDurableWriteOwnershipExecutionConflict("Phase AH rollback reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_durable_write_ownership_lease(
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
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Only an active Phase AH lease can be rolled back"
        )
    route = _load_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    if route is None or not _route_is_exact_active(route, lease):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH active durable write route drifted; refusing unsafe rollback"
        )

    route.write_mode = "local_only"
    route.active_durable_write_ownership_lease_id = None
    route.route_version += 1
    route.durable_write_authority_created = False
    route.write_path_switched = False
    route.changed_by_id = rolled_back_by_id
    route.changed_at = current
    db.flush()

    lease.status = "rolled_back"
    lease.durable_write_ownership_active = False
    lease.durable_write_authority_created = False
    lease.write_path_switched = False
    lease.terminal_by_id = rolled_back_by_id
    lease.terminal_at = current
    lease.terminal_reason = normalized_reason
    db.flush()

    receipt = _add_receipt(
        db,
        lease,
        phase="rolled_back",
        from_write_mode="recovery_primary",
        to_write_mode="local_only",
        route_version=route.route_version,
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        now=current,
    )
    return lease, receipt, "rolled_back"


def reconcile_durable_write_ownership(
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
        raise RecoveryDurableWriteOwnershipExecutionConflict("Phase AH reconciliation reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_durable_write_ownership_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status != "active":
        return lease, _terminal_receipt(db, lease=lease), "unchanged"
    route = _load_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    if route is None:
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH durable write route is missing during reconciliation"
        )
    if _route_is_exact_active(route, lease):
        return lease, None, "unchanged"
    if not _route_is_safe_local(route):
        raise RecoveryDurableWriteOwnershipExecutionConflict(
            "Phase AH durable write route drifted to an unsafe state"
        )

    lease.status = "invalidated"
    lease.durable_write_ownership_active = False
    lease.durable_write_authority_created = False
    lease.write_path_switched = False
    lease.terminal_by_id = actor_id
    lease.terminal_at = current
    lease.terminal_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(
        db,
        lease,
        phase="invalidated",
        from_write_mode="local_only",
        to_write_mode="local_only",
        route_version=route.route_version,
        actor_id=actor_id,
        reason=normalized_reason,
        now=current,
    )
    return lease, receipt, "invalidated"


def list_durable_write_ownership_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
):
    get_durable_write_ownership_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipReceipt)
            .where(
                EvidenceRecoveryDurableWriteOwnershipReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.document_id == document_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryDurableWriteOwnershipReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableWriteOwnershipReceipt.id.asc(),
            )
        ).all()
    )
