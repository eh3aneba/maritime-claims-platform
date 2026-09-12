from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authoritative_storage_ownership_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization,
    EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt,
)
from app.modules.documents.recovery_authoritative_storage_ownership_authorization_service import (
    RecoveryAuthoritativeStorageOwnershipAuthorizationConflict,
    RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound,
    RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable,
    _fresh_ai,
    _matches_authorization,
    get_authoritative_storage_ownership_authorization,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipLease,
    EvidenceRecoveryAuthoritativeStorageOwnershipReceipt,
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


AUTHORITATIVE_STORAGE_OWNERSHIP_WINDOW = timedelta(hours=72)


class RecoveryAuthoritativeStorageOwnershipExecutionError(RuntimeError):
    pass


class RecoveryAuthoritativeStorageOwnershipExecutionNotFound(
    RecoveryAuthoritativeStorageOwnershipExecutionError
):
    pass


class RecoveryAuthoritativeStorageOwnershipExecutionConflict(
    RecoveryAuthoritativeStorageOwnershipExecutionError
):
    pass


class RecoveryAuthoritativeStorageOwnershipExecutionUnavailable(
    RecoveryAuthoritativeStorageOwnershipExecutionError
):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approved_receipt(
    db: Session,
    *,
    authorization: EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization,
) -> EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt).where(
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.organization_id
                == authorization.organization_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.claim_id
                == authorization.claim_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.document_id
                == authorization.document_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.authorization_id
                == authorization.id,
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Approved Phase AJ authorization must have exactly one approved receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            receipt.actor_id == authorization.approved_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.phase_ai_health_qualification_id == authorization.phase_ai_health_qualification_id,
            receipt.phase_ai_health_qualification_hash
            == authorization.phase_ai_health_qualification_hash,
            receipt.phase_ai_health_receipt_hash == authorization.phase_ai_health_receipt_hash,
            receipt.current_authority_kind == "local_evidence",
            receipt.target_authority_kind == "recovery_storage",
            receipt.local_authoritative is True,
            receipt.storage_write_performed is False,
            receipt.route_mutation_performed is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.physical_disposal_authorized is False,
            receipt.s3_put_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_overwrite_performed is False,
            receipt.local_move_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AJ approved receipt lineage is inconsistent"
        )
    return receipt


def _fresh_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    require_unexpired: bool,
    now: datetime,
):
    try:
        authorization = get_authoritative_storage_ownership_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            for_update=True,
        )
    except RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipExecutionNotFound(str(exc)) from exc

    if not all(
        (
            authorization.status == "approved",
            authorization.health_state == "healthy",
            authorization.max_execution_windows == 1,
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.authorization_expires_at is not None,
            authorization.current_authority_kind == "local_evidence",
            authorization.target_authority_kind == "recovery_storage",
            authorization.local_authoritative is True,
            authorization.storage_write_performed is False,
            authorization.route_mutation_performed is False,
            authorization.document_storage_key_mutated is False,
            authorization.authoritative_storage_changed is False,
            authorization.destructive_action_performed is False,
            authorization.physical_disposal_authorized is False,
            authorization.s3_put_performed is False,
            authorization.s3_copy_performed is False,
            authorization.s3_delete_performed is False,
            authorization.local_overwrite_performed is False,
            authorization.local_move_performed is False,
            authorization.local_delete_performed is False,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AK requires one exact approved healthy Phase AJ authorization"
        )
    if require_unexpired and now >= _as_utc(authorization.authorization_expires_at):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AJ authorization expired before Phase AK activation"
        )

    approved_receipt = _approved_receipt(db, authorization=authorization)
    try:
        q, ai_receipt, snapshot = _fresh_ai(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=authorization.phase_ai_health_qualification_id,
        )
    except RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable as exc:
        raise RecoveryAuthoritativeStorageOwnershipExecutionUnavailable(str(exc)) from exc
    except RecoveryAuthoritativeStorageOwnershipAuthorizationNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipExecutionNotFound(str(exc)) from exc
    except RecoveryAuthoritativeStorageOwnershipAuthorizationConflict as exc:
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(str(exc)) from exc

    if not _matches_authorization(authorization, q, ai_receipt, snapshot):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AJ authorization snapshot drifted before Phase AK execution"
        )
    return authorization, approved_receipt, q, snapshot


def _route_stmt(*, organization_id: UUID, claim_id: UUID, document_id: UUID):
    return select(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).where(
        EvidenceRecoveryAuthoritativeStorageOwnershipRoute.organization_id == organization_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipRoute.claim_id == claim_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipRoute.document_id == document_id,
    )


def _get_or_create_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    actor_id: UUID,
    now: datetime,
):
    route = db.scalar(_route_stmt(organization_id=organization_id, claim_id=claim_id, document_id=document_id).with_for_update())
    if route is None:
        route = EvidenceRecoveryAuthoritativeStorageOwnershipRoute(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authority_kind="local_evidence",
            active_authority_lease_id=None,
            route_version=1,
            local_authoritative=True,
            recovery_authoritative=False,
            authoritative_storage_changed=False,
            changed_by_id=actor_id,
            changed_at=now,
            local_evidence_preserved=True,
            storage_write_performed=False,
            read_path_switched=False,
            write_route_mutation_performed=False,
            document_storage_key_mutated=False,
            destructive_action_performed=False,
            physical_disposal_authorized=False,
            s3_put_performed=False,
            s3_copy_performed=False,
            s3_delete_performed=False,
            local_overwrite_performed=False,
            local_move_performed=False,
            local_delete_performed=False,
        )
        db.add(route)
        db.flush()
    return route


def get_authoritative_storage_ownership_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
):
    route = db.scalar(_route_stmt(organization_id=organization_id, claim_id=claim_id, document_id=document_id))
    if route is None:
        raise RecoveryAuthoritativeStorageOwnershipExecutionNotFound(
            "Phase AK authoritative-storage ownership route not found"
        )
    return route


def get_authoritative_storage_ownership_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryAuthoritativeStorageOwnershipLease).where(
        EvidenceRecoveryAuthoritativeStorageOwnershipLease.id == lease_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipLease.organization_id == organization_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipLease.claim_id == claim_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryAuthoritativeStorageOwnershipExecutionNotFound(
            "Phase AK authoritative-storage ownership lease not found"
        )
    return lease


def list_authoritative_storage_ownership_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
):
    get_authoritative_storage_ownership_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageOwnershipReceipt)
            .where(
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.organization_id == organization_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.claim_id == claim_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.document_id == document_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.lease_id == lease_id,
            )
            .order_by(EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.transitioned_at)
        ).all()
    )


def _forbidden_activators(a) -> set[UUID]:
    actors = {
        a.requested_by_id,
        a.phase_ai_requested_by_id,
        a.phase_ai_qualified_by_id,
        a.phase_ah_activated_by_id,
        a.phase_ag_requested_by_id,
        a.phase_ag_approved_by_id,
        a.phase_af_requested_by_id,
        a.phase_af_qualified_by_id,
        a.phase_ae_activated_by_id,
        a.phase_ad_requested_by_id,
        a.phase_ad_approved_by_id,
    }
    if a.approved_by_id is not None:
        actors.add(a.approved_by_id)
    return actors


def _activation_snapshot_hash(a, approval_receipt, q, snapshot, route) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(a.id),
            "authorization_hash": a.authorization_hash,
            "authorization_approval_receipt_id": str(approval_receipt.id),
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "phase_ai_health_qualification_id": str(q.id),
            "phase_ai_health_qualification_hash": q.health_qualification_hash,
            "durable_write_ownership_lease_id": str(snapshot.lease.id),
            "durable_write_ownership_lease_hash": snapshot.lease.lease_hash,
            "replica_id": str(a.replica_id),
            "replica_hash": a.replica_hash,
            "source_file_hash": a.source_file_hash,
            "source_file_size_bytes": a.source_file_size_bytes,
            "observed_local_hash": a.observed_local_hash,
            "observed_recovery_hash": a.observed_recovery_hash,
            "read_route_version": a.read_route_version_at_request,
            "experimental_write_route_version": a.experimental_write_route_version_at_request,
            "durable_route_version": a.durable_route_version_at_request,
            "authority_route_version_before_activation": route.route_version,
            "from_authority_kind": "local_evidence",
            "to_authority_kind": "recovery_storage",
            "local_evidence_preserved": True,
            "physical_disposal_authorized": False,
        }
    )


def _lease_hash(*, a, activation_snapshot_hash: str, activated_by_id: UUID, activated_at: datetime, expires_at: datetime) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(a.id),
            "authorization_hash": a.authorization_hash,
            "activation_snapshot_hash": activation_snapshot_hash,
            "activated_by_id": str(activated_by_id),
            "activated_at": _utc_iso(activated_at),
            "expires_at": _utc_iso(expires_at),
            "mode": "phase_ak_authoritative_storage_ownership_execution",
        }
    )


def _receipt_hash(
    lease,
    *,
    phase: str,
    from_kind: str,
    to_kind: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "phase": phase,
            "from_authority_kind": from_kind,
            "to_authority_kind": to_kind,
            "route_version": route_version,
            "authorization_hash": lease.authorization_hash,
            "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
            "phase_ai_health_qualification_hash": lease.phase_ai_health_qualification_hash,
            "source_file_hash": lease.source_file_hash,
            "activation_snapshot_hash": lease.activation_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_evidence_preserved": True,
            "storage_write_performed": False,
            "read_path_switched": False,
            "write_route_mutation_performed": False,
            "document_storage_key_mutated": False,
            "destructive_action_performed": False,
            "physical_disposal_authorized": False,
        }
    )


def _add_receipt(
    db: Session,
    lease,
    *,
    phase: str,
    from_kind: str,
    to_kind: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    now: datetime,
):
    active = phase == "activated"
    receipt = EvidenceRecoveryAuthoritativeStorageOwnershipReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        lease_id=lease.id,
        authorization_id=lease.authorization_id,
        phase=phase,
        from_authority_kind=from_kind,
        to_authority_kind=to_kind,
        route_version=route_version,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        phase_ai_health_qualification_hash=lease.phase_ai_health_qualification_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        activation_snapshot_hash=lease.activation_snapshot_hash,
        lease_hash=lease.lease_hash,
        receipt_hash=_receipt_hash(
            lease,
            phase=phase,
            from_kind=from_kind,
            to_kind=to_kind,
            route_version=route_version,
            actor_id=actor_id,
            reason=reason,
            transitioned_at=now,
        ),
        local_authoritative=not active,
        recovery_authoritative=active,
        authoritative_storage_changed=active,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_evidence_preserved=True,
        storage_write_performed=False,
        read_path_switched=False,
        write_route_mutation_performed=False,
        document_storage_key_mutated=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
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


def activate_authoritative_storage_ownership(
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
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict("Phase AK activation reason is required")
    current = _as_utc(now or _utc_now())

    existing = db.scalar(
        select(EvidenceRecoveryAuthoritativeStorageOwnershipLease)
        .where(
            EvidenceRecoveryAuthoritativeStorageOwnershipLease.organization_id == organization_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipLease.claim_id == claim_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipLease.document_id == document_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipLease.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.activated_by_id == activated_by_id and existing.activation_reason == normalized_reason:
            return existing, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AJ authorization already has a Phase AK execution lease"
        )

    a, approval_receipt, q, snapshot = _fresh_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        require_unexpired=True,
        now=current,
    )
    if activated_by_id in _forbidden_activators(a):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AK activator must be independent from AJ, AI, AH, AG, AF, AE and AD governance actors"
        )

    route = _get_or_create_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        actor_id=activated_by_id,
        now=current,
    )
    if not all(
        (
            route.authority_kind == "local_evidence",
            route.active_authority_lease_id is None,
            route.local_authoritative is True,
            route.recovery_authoritative is False,
            route.authoritative_storage_changed is False,
            route.local_evidence_preserved is True,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AK requires exact clean local authoritative-storage route"
        )

    before_version = route.route_version
    after_version = before_version + 1
    activation_snapshot_hash = _activation_snapshot_hash(a, approval_receipt, q, snapshot, route)
    expires_at = current + AUTHORITATIVE_STORAGE_OWNERSHIP_WINDOW
    lease_hash = _lease_hash(
        a=a,
        activation_snapshot_hash=activation_snapshot_hash,
        activated_by_id=activated_by_id,
        activated_at=current,
        expires_at=expires_at,
    )
    lease = EvidenceRecoveryAuthoritativeStorageOwnershipLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=a.id,
        authorization_approval_receipt_id=approval_receipt.id,
        phase_ai_health_qualification_id=a.phase_ai_health_qualification_id,
        durable_write_ownership_lease_id=a.durable_write_ownership_lease_id,
        replica_id=a.replica_id,
        authorization_hash=a.authorization_hash,
        authorization_approval_receipt_hash=approval_receipt.receipt_hash,
        phase_ai_health_qualification_hash=a.phase_ai_health_qualification_hash,
        durable_write_ownership_lease_hash=a.durable_write_ownership_lease_hash,
        replica_hash=a.replica_hash,
        source_file_hash=a.source_file_hash,
        source_file_size_bytes=a.source_file_size_bytes,
        local_storage_key_fingerprint=a.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=a.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=a.candidate_storage_key_fingerprint,
        source_authority_fingerprint=a.source_authority_fingerprint,
        candidate_authority_fingerprint=a.candidate_authority_fingerprint,
        configuration_fingerprint=a.configuration_fingerprint,
        observed_local_hash=a.observed_local_hash,
        observed_local_size_bytes=a.observed_local_size_bytes,
        observed_recovery_hash=a.observed_recovery_hash,
        observed_recovery_size_bytes=a.observed_recovery_size_bytes,
        observed_recovery_etag=a.observed_recovery_etag,
        read_route_version_at_activation=a.read_route_version_at_request,
        experimental_write_route_version_at_activation=a.experimental_write_route_version_at_request,
        durable_route_version_at_activation=a.durable_route_version_at_request,
        authority_route_version_before_activation=before_version,
        authority_route_version_after_activation=after_version,
        activation_snapshot_hash=activation_snapshot_hash,
        lease_hash=lease_hash,
        status="active",
        ownership_transition_active=True,
        local_authoritative=False,
        recovery_authoritative=True,
        authoritative_storage_changed=True,
        activated_by_id=activated_by_id,
        activated_at=current,
        expires_at=expires_at,
        activation_reason=normalized_reason,
        local_evidence_preserved=True,
        storage_write_performed=False,
        read_path_switched=False,
        write_route_mutation_performed=False,
        document_storage_key_mutated=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(lease)
    db.flush()

    route.authority_kind = "recovery_storage"
    route.active_authority_lease_id = lease.id
    route.route_version = after_version
    route.local_authoritative = False
    route.recovery_authoritative = True
    route.authoritative_storage_changed = True
    route.changed_by_id = activated_by_id
    route.changed_at = current
    db.flush()

    receipt = _add_receipt(
        db,
        lease,
        phase="activated",
        from_kind="local_evidence",
        to_kind="recovery_storage",
        route_version=after_version,
        actor_id=activated_by_id,
        reason=normalized_reason,
        now=current,
    )
    return lease, receipt, "activated"


def _restore_local_authority(
    db: Session,
    *,
    lease,
    route,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
):
    route.authority_kind = "local_evidence"
    route.active_authority_lease_id = None
    route.route_version += 1
    route.local_authoritative = True
    route.recovery_authoritative = False
    route.authoritative_storage_changed = False
    route.changed_by_id = actor_id
    route.changed_at = now

    lease.status = phase
    lease.ownership_transition_active = False
    lease.local_authoritative = True
    lease.recovery_authoritative = False
    lease.authoritative_storage_changed = False
    lease.terminal_by_id = actor_id
    lease.terminal_at = now
    lease.terminal_reason = reason
    db.flush()

    receipt = _add_receipt(
        db,
        lease,
        phase=phase,
        from_kind="recovery_storage",
        to_kind="local_evidence",
        route_version=route.route_version,
        actor_id=actor_id,
        reason=reason,
        now=now,
    )
    return lease, receipt, phase


def rollback_authoritative_storage_ownership(
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
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict("Phase AK rollback reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_authoritative_storage_ownership_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status == "rolled_back":
        return lease, None, "unchanged"
    if lease.status != "active":
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Only an active Phase AK ownership lease can be rolled back"
        )
    route = db.scalar(_route_stmt(organization_id=organization_id, claim_id=claim_id, document_id=document_id).with_for_update())
    if route is None:
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict("Phase AK authority route is missing")
    if not all(
        (
            route.authority_kind == "recovery_storage",
            route.active_authority_lease_id == lease.id,
            route.route_version == lease.authority_route_version_after_activation,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict(
            "Phase AK rollback route binding drifted"
        )
    return _restore_local_authority(
        db,
        lease=lease,
        route=route,
        phase="rolled_back",
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        now=current,
    )


def reconcile_authoritative_storage_ownership(
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
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict("Phase AK reconciliation reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_authoritative_storage_ownership_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status != "active":
        return lease, None, "unchanged"
    route = db.scalar(_route_stmt(organization_id=organization_id, claim_id=claim_id, document_id=document_id).with_for_update())
    if route is None:
        raise RecoveryAuthoritativeStorageOwnershipExecutionConflict("Phase AK authority route is missing")

    if current >= _as_utc(lease.expires_at):
        return _restore_local_authority(
            db,
            lease=lease,
            route=route,
            phase="expired",
            actor_id=actor_id,
            reason="Phase AK bounded authoritative-storage ownership window expired",
            now=current,
        )

    route_ok = all(
        (
            route.authority_kind == "recovery_storage",
            route.active_authority_lease_id == lease.id,
            route.route_version == lease.authority_route_version_after_activation,
            route.local_authoritative is False,
            route.recovery_authoritative is True,
            route.authoritative_storage_changed is True,
            route.local_evidence_preserved is True,
        )
    )
    try:
        a, approval_receipt, q, snapshot = _fresh_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=lease.authorization_id,
            require_unexpired=False,
            now=current,
        )
        lineage_ok = all(
            (
                a.id == lease.authorization_id,
                approval_receipt.id == lease.authorization_approval_receipt_id,
                approval_receipt.receipt_hash == lease.authorization_approval_receipt_hash,
                q.id == lease.phase_ai_health_qualification_id,
                q.health_qualification_hash == lease.phase_ai_health_qualification_hash,
                snapshot.lease.id == lease.durable_write_ownership_lease_id,
                snapshot.lease.lease_hash == lease.durable_write_ownership_lease_hash,
                a.replica_id == lease.replica_id,
                a.replica_hash == lease.replica_hash,
                a.source_file_hash == lease.source_file_hash,
                a.source_file_size_bytes == lease.source_file_size_bytes,
                a.observed_local_hash == lease.observed_local_hash,
                a.observed_recovery_hash == lease.observed_recovery_hash,
            )
        )
    except RecoveryAuthoritativeStorageOwnershipExecutionUnavailable:
        raise
    except (
        RecoveryAuthoritativeStorageOwnershipExecutionNotFound,
        RecoveryAuthoritativeStorageOwnershipExecutionConflict,
    ):
        lineage_ok = False

    if not route_ok or not lineage_ok:
        return _restore_local_authority(
            db,
            lease=lease,
            route=route,
            phase="invalidated",
            actor_id=actor_id,
            reason=f"{normalized_reason}: Phase AK route, lineage or byte-integrity drift detected",
            now=current,
        )
    return lease, None, "unchanged"
