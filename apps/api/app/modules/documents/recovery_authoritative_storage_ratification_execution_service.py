from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageRatificationAuthorization,
    EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_service import (
    RecoveryAuthoritativeStorageRatificationAuthorizationConflict,
    RecoveryAuthoritativeStorageRatificationAuthorizationNotFound,
    RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable,
    _fresh_al,
    _matches_authorization,
    get_authoritative_storage_ratification_authorization,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_models import (
    EvidenceRecoveryAuthoritativeStorageRatification,
    EvidenceRecoveryAuthoritativeStorageRatificationReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


class RecoveryAuthoritativeStorageRatificationExecutionError(RuntimeError):
    pass


class RecoveryAuthoritativeStorageRatificationExecutionNotFound(
    RecoveryAuthoritativeStorageRatificationExecutionError
):
    pass


class RecoveryAuthoritativeStorageRatificationExecutionConflict(
    RecoveryAuthoritativeStorageRatificationExecutionError
):
    pass


class RecoveryAuthoritativeStorageRatificationExecutionUnavailable(
    RecoveryAuthoritativeStorageRatificationExecutionError
):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approved_am_receipt(
    db: Session,
    *,
    authorization: EvidenceRecoveryAuthoritativeStorageRatificationAuthorization,
) -> EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt).where(
                EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt.organization_id
                == authorization.organization_id,
                EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt.claim_id
                == authorization.claim_id,
                EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt.document_id
                == authorization.document_id,
                EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt.authorization_id
                == authorization.id,
                EvidenceRecoveryAuthoritativeStorageRatificationAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Approved Phase AM authorization must have exactly one approved receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.ratification_authorized is True,
            receipt.actor_id == authorization.approved_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.phase_al_health_qualification_id == authorization.phase_al_health_qualification_id,
            receipt.phase_al_health_qualification_hash == authorization.phase_al_health_qualification_hash,
            receipt.phase_al_health_receipt_hash == authorization.phase_al_health_receipt_hash,
            receipt.current_authority_kind == "recovery_storage",
            receipt.target_ratification_kind == "durable_recovery_storage",
            receipt.observed_local_authoritative is False,
            receipt.observed_recovery_authoritative is True,
            receipt.observed_authoritative_storage_changed is True,
            receipt.ratification_authorized is True,
            receipt.local_evidence_preserved is True,
            receipt.storage_write_performed is False,
            receipt.route_mutation_performed is False,
            receipt.ownership_mutation_performed is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
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
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AM approved receipt lineage is inconsistent"
        )
    return receipt


def _fresh_am(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    now: datetime,
):
    try:
        a = get_authoritative_storage_ratification_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            for_update=True,
        )
    except RecoveryAuthoritativeStorageRatificationAuthorizationNotFound as exc:
        raise RecoveryAuthoritativeStorageRatificationExecutionNotFound(str(exc)) from exc

    if not all(
        (
            a.status == "approved",
            a.health_state == "healthy",
            a.max_execution_windows == 1,
            a.ratification_authorized is True,
            a.approved_by_id is not None,
            a.approved_at is not None,
            a.authorization_expires_at is not None,
            a.current_authority_kind == "recovery_storage",
            a.target_ratification_kind == "durable_recovery_storage",
            a.observed_local_authoritative is False,
            a.observed_recovery_authoritative is True,
            a.observed_authoritative_storage_changed is True,
            a.local_evidence_preserved is True,
            a.storage_write_performed is False,
            a.route_mutation_performed is False,
            a.ownership_mutation_performed is False,
            a.read_path_switched is False,
            a.write_path_switched is False,
            a.document_storage_key_mutated is False,
            a.destructive_action_performed is False,
            a.physical_disposal_authorized is False,
            a.s3_put_performed is False,
            a.s3_copy_performed is False,
            a.s3_delete_performed is False,
            a.local_overwrite_performed is False,
            a.local_move_performed is False,
            a.local_delete_performed is False,
        )
    ):
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AN requires one exact approved healthy Phase AM authorization"
        )
    if now >= _as_utc(a.authorization_expires_at):
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AM authorization expired before Phase AN ratification"
        )

    approval_receipt = _approved_am_receipt(db, authorization=a)
    try:
        q, al_receipt, snapshot = _fresh_al(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=a.phase_al_health_qualification_id,
            now=now,
        )
    except RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable as exc:
        raise RecoveryAuthoritativeStorageRatificationExecutionUnavailable(str(exc)) from exc
    except RecoveryAuthoritativeStorageRatificationAuthorizationNotFound as exc:
        raise RecoveryAuthoritativeStorageRatificationExecutionNotFound(str(exc)) from exc
    except RecoveryAuthoritativeStorageRatificationAuthorizationConflict as exc:
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(str(exc)) from exc

    if not _matches_authorization(a, q, al_receipt, snapshot):
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AM authorization snapshot drifted before Phase AN ratification"
        )
    return a, approval_receipt, q, al_receipt, snapshot


def _forbidden_executors(a) -> set[UUID]:
    actors = {
        a.requested_by_id,
        a.phase_al_requested_by_id,
        a.phase_al_qualified_by_id,
        a.phase_ak_activated_by_id,
        a.phase_aj_requested_by_id,
        a.phase_aj_approved_by_id,
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


def _execution_snapshot_hash(a, approval_receipt, q, al_receipt, snapshot, route) -> str:
    lease = snapshot.lease
    return _canonical_hash(
        {
            "authorization_id": str(a.id),
            "authorization_hash": a.authorization_hash,
            "authorization_approval_receipt_id": str(approval_receipt.id),
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "phase_al_health_qualification_id": str(q.id),
            "phase_al_health_qualification_hash": q.health_qualification_hash,
            "phase_al_health_receipt_id": str(al_receipt.id),
            "phase_al_health_receipt_hash": al_receipt.receipt_hash,
            "phase_al_integrity_proof_hash": q.integrity_proof_hash,
            "authoritative_storage_ownership_lease_id": str(lease.id),
            "authoritative_storage_ownership_lease_hash": lease.lease_hash,
            "phase_aj_authorization_id": str(snapshot.authorization.id),
            "phase_aj_authorization_hash": snapshot.authorization.authorization_hash,
            "phase_ai_health_qualification_id": str(q.phase_ai_health_qualification_id),
            "phase_ai_health_qualification_hash": q.phase_ai_health_qualification_hash,
            "durable_write_ownership_lease_id": str(q.durable_write_ownership_lease_id),
            "durable_write_ownership_lease_hash": q.durable_write_ownership_lease_hash,
            "replica_id": str(q.replica_id),
            "replica_hash": q.replica_hash,
            "source_file_hash": q.source_file_hash,
            "source_file_size_bytes": q.source_file_size_bytes,
            "observed_local_hash": q.observed_local_hash,
            "observed_local_size_bytes": q.observed_local_size_bytes,
            "observed_recovery_hash": q.observed_recovery_hash,
            "observed_recovery_size_bytes": q.observed_recovery_size_bytes,
            "observed_recovery_etag": q.observed_recovery_etag,
            "authority_route_version_before_ratification": route.route_version,
            "authority_kind": "recovery_storage",
            "authority_tenure_before": "bounded_recovery",
            "authority_tenure_after": "durable_recovery",
            "read_route_version": q.read_route_version_at_request,
            "experimental_write_route_version": q.experimental_write_route_version_at_request,
            "durable_route_version": q.durable_route_version_at_request,
            "local_evidence_preserved": True,
            "storage_write_performed": False,
            "physical_disposal_authorized": False,
        }
    )


def _ratification_hash(*, authorization_hash: str, execution_snapshot_hash: str, executed_by_id: UUID, executed_at: datetime, reason: str) -> str:
    return _canonical_hash(
        {
            "authorization_hash": authorization_hash,
            "execution_snapshot_hash": execution_snapshot_hash,
            "executed_by_id": str(executed_by_id),
            "executed_at": _utc_iso(executed_at),
            "execution_reason": reason,
            "authority_tenure": "durable_recovery",
            "mode": "phase_an_authoritative_storage_ratification_execution",
        }
    )


def _receipt_hash(r, *, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "ratification_id": str(r.id),
            "authorization_id": str(r.authorization_id),
            "phase": "ratified",
            "from_authority_kind": "recovery_storage",
            "to_authority_kind": "recovery_storage",
            "from_authority_tenure": "bounded_recovery",
            "to_authority_tenure": "durable_recovery",
            "route_version": r.authority_route_version_after_ratification,
            "authorization_hash": r.authorization_hash,
            "authorization_approval_receipt_hash": r.authorization_approval_receipt_hash,
            "phase_al_health_qualification_hash": r.phase_al_health_qualification_hash,
            "source_file_hash": r.source_file_hash,
            "source_file_size_bytes": r.source_file_size_bytes,
            "execution_snapshot_hash": r.execution_snapshot_hash,
            "ratification_hash": r.ratification_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "ratification_active": True,
            "durable_authority_created": True,
            "local_authoritative": False,
            "recovery_authoritative": True,
            "authoritative_storage_changed": True,
            "local_evidence_preserved": True,
            "storage_write_performed": False,
            "route_mutation_performed": True,
            "ownership_mutation_performed": True,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "destructive_action_performed": False,
            "physical_disposal_authorized": False,
        }
    )


def _add_receipt(db: Session, r, *, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryAuthoritativeStorageRatificationReceipt(
        organization_id=r.organization_id,
        claim_id=r.claim_id,
        document_id=r.document_id,
        ratification_id=r.id,
        authorization_id=r.authorization_id,
        phase="ratified",
        from_authority_kind="recovery_storage",
        to_authority_kind="recovery_storage",
        from_authority_tenure="bounded_recovery",
        to_authority_tenure="durable_recovery",
        route_version=r.authority_route_version_after_ratification,
        authorization_hash=r.authorization_hash,
        authorization_approval_receipt_hash=r.authorization_approval_receipt_hash,
        phase_al_health_qualification_hash=r.phase_al_health_qualification_hash,
        source_file_hash=r.source_file_hash,
        source_file_size_bytes=r.source_file_size_bytes,
        execution_snapshot_hash=r.execution_snapshot_hash,
        ratification_hash=r.ratification_hash,
        receipt_hash=_receipt_hash(r, actor_id=actor_id, reason=reason, transitioned_at=now),
        ratification_active=True,
        durable_authority_created=True,
        local_authoritative=False,
        recovery_authoritative=True,
        authoritative_storage_changed=True,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_evidence_preserved=True,
        storage_write_performed=False,
        route_mutation_performed=True,
        ownership_mutation_performed=True,
        read_path_switched=False,
        write_path_switched=False,
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


def _route_stmt(*, organization_id: UUID, claim_id: UUID, document_id: UUID):
    return select(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).where(
        EvidenceRecoveryAuthoritativeStorageOwnershipRoute.organization_id == organization_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipRoute.claim_id == claim_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipRoute.document_id == document_id,
    )


def get_authoritative_storage_ratification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    ratification_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryAuthoritativeStorageRatification).where(
        EvidenceRecoveryAuthoritativeStorageRatification.id == ratification_id,
        EvidenceRecoveryAuthoritativeStorageRatification.organization_id == organization_id,
        EvidenceRecoveryAuthoritativeStorageRatification.claim_id == claim_id,
        EvidenceRecoveryAuthoritativeStorageRatification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    r = db.scalar(stmt)
    if r is None:
        raise RecoveryAuthoritativeStorageRatificationExecutionNotFound(
            "Phase AN authoritative-storage ratification not found"
        )
    return r


def list_authoritative_storage_ratification_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    ratification_id: UUID,
):
    get_authoritative_storage_ratification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        ratification_id=ratification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageRatificationReceipt)
            .where(
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.organization_id == organization_id,
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.claim_id == claim_id,
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.document_id == document_id,
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.ratification_id == ratification_id,
            )
            .order_by(EvidenceRecoveryAuthoritativeStorageRatificationReceipt.transitioned_at)
        ).all()
    )


def execute_authoritative_storage_ratification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    executed_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AN execution reason is required"
        )
    current = _as_utc(now or _utc_now())

    existing = db.scalar(
        select(EvidenceRecoveryAuthoritativeStorageRatification)
        .where(
            EvidenceRecoveryAuthoritativeStorageRatification.organization_id == organization_id,
            EvidenceRecoveryAuthoritativeStorageRatification.claim_id == claim_id,
            EvidenceRecoveryAuthoritativeStorageRatification.document_id == document_id,
            EvidenceRecoveryAuthoritativeStorageRatification.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.executed_by_id != executed_by_id or existing.execution_reason != normalized_reason:
            raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
                "Phase AM authorization already has a different Phase AN ratification execution"
            )
        route = db.scalar(
            _route_stmt(
                organization_id=organization_id,
                claim_id=claim_id,
                document_id=document_id,
            ).with_for_update()
        )
        if route is None or not all(
            (
                existing.status == "ratified",
                existing.ratification_active is True,
                existing.durable_authority_created is True,
                route.authority_kind == "recovery_storage",
                route.authority_tenure == "durable_recovery",
                route.active_authority_lease_id is None,
                route.durable_ratification_id == existing.id,
                route.route_version == existing.authority_route_version_after_ratification,
                route.local_authoritative is False,
                route.recovery_authoritative is True,
                route.authoritative_storage_changed is True,
                route.local_evidence_preserved is True,
            )
        ):
            raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
                "Phase AN replay detected durable authority route drift"
            )
        return existing, route, None, "unchanged"

    a, approval_receipt, q, al_receipt, snapshot = _fresh_am(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        now=current,
    )
    if executed_by_id in _forbidden_executors(a):
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AN executor must be independent from AM, AL, AK, AJ, AI, AH, AG, AF, AE and AD actors"
        )

    route = db.scalar(
        _route_stmt(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        ).with_for_update()
    )
    if route is None:
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AN authoritative-storage route is missing"
        )
    lease = snapshot.lease
    if not all(
        (
            route.id == snapshot.authority_route.id,
            route.authority_kind == "recovery_storage",
            route.authority_tenure == "bounded_recovery",
            route.active_authority_lease_id == lease.id,
            route.durable_ratification_id is None,
            route.route_version == lease.authority_route_version_after_activation,
            route.route_version == a.authority_route_version_at_request,
            route.local_authoritative is False,
            route.recovery_authoritative is True,
            route.authoritative_storage_changed is True,
            route.local_evidence_preserved is True,
            route.storage_write_performed is False,
            route.read_path_switched is False,
            route.write_route_mutation_performed is False,
            route.document_storage_key_mutated is False,
            route.destructive_action_performed is False,
            route.physical_disposal_authorized is False,
            lease.status == "active",
            lease.ownership_transition_active is True,
            lease.local_authoritative is False,
            lease.recovery_authoritative is True,
            lease.authoritative_storage_changed is True,
        )
    ):
        raise RecoveryAuthoritativeStorageRatificationExecutionConflict(
            "Phase AN requires exact bounded Phase AK recovery-storage authority"
        )

    before_version = route.route_version
    after_version = before_version + 1
    execution_snapshot_hash = _execution_snapshot_hash(a, approval_receipt, q, al_receipt, snapshot, route)
    ratification_hash = _ratification_hash(
        authorization_hash=a.authorization_hash,
        execution_snapshot_hash=execution_snapshot_hash,
        executed_by_id=executed_by_id,
        executed_at=current,
        reason=normalized_reason,
    )
    r = EvidenceRecoveryAuthoritativeStorageRatification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=a.id,
        authorization_approval_receipt_id=approval_receipt.id,
        phase_al_health_qualification_id=q.id,
        authoritative_storage_ownership_lease_id=lease.id,
        phase_aj_authorization_id=a.phase_aj_authorization_id,
        phase_ai_health_qualification_id=a.phase_ai_health_qualification_id,
        durable_write_ownership_lease_id=a.durable_write_ownership_lease_id,
        replica_id=a.replica_id,
        authorization_hash=a.authorization_hash,
        authorization_approval_receipt_hash=approval_receipt.receipt_hash,
        phase_al_health_qualification_hash=q.health_qualification_hash,
        phase_al_health_receipt_hash=al_receipt.receipt_hash,
        phase_al_integrity_proof_hash=q.integrity_proof_hash,
        authoritative_storage_ownership_lease_hash=lease.lease_hash,
        phase_aj_authorization_hash=a.phase_aj_authorization_hash,
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
        authority_route_version_before_ratification=before_version,
        authority_route_version_after_ratification=after_version,
        read_route_version_at_ratification=a.read_route_version_at_request,
        experimental_write_route_version_at_ratification=a.experimental_write_route_version_at_request,
        durable_route_version_at_ratification=a.durable_route_version_at_request,
        execution_snapshot_hash=execution_snapshot_hash,
        ratification_hash=ratification_hash,
        status="ratified",
        authority_kind="recovery_storage",
        authority_tenure="durable_recovery",
        ratification_active=True,
        durable_authority_created=True,
        local_authoritative=False,
        recovery_authoritative=True,
        authoritative_storage_changed=True,
        executed_by_id=executed_by_id,
        executed_at=current,
        execution_reason=normalized_reason,
        local_evidence_preserved=True,
        storage_write_performed=False,
        route_mutation_performed=True,
        ownership_mutation_performed=True,
        read_path_switched=False,
        write_path_switched=False,
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
    db.add(r)
    db.flush()

    lease.status = "ratified"
    lease.ownership_transition_active = False
    lease.local_authoritative = False
    lease.recovery_authoritative = True
    lease.authoritative_storage_changed = True
    lease.terminal_by_id = executed_by_id
    lease.terminal_at = current
    lease.terminal_reason = normalized_reason

    route.authority_kind = "recovery_storage"
    route.authority_tenure = "durable_recovery"
    route.active_authority_lease_id = None
    route.durable_ratification_id = r.id
    route.route_version = after_version
    route.local_authoritative = False
    route.recovery_authoritative = True
    route.authoritative_storage_changed = True
    route.changed_by_id = executed_by_id
    route.changed_at = current
    db.flush()

    receipt = _add_receipt(db, r, actor_id=executed_by_id, reason=normalized_reason, now=current)
    return r, route, receipt, "ratified"