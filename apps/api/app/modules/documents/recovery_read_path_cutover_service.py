from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_cutover_execution_models import (
    EvidenceRecoveryCutoverExecutionLease,
    EvidenceRecoveryCutoverExecutionReceipt,
)
from app.modules.documents.recovery_cutover_execution_service import (
    RecoveryCutoverExecutionConflict,
    RecoveryCutoverExecutionNotFound,
    RecoveryCutoverExecutionUnavailable,
    _get_lease,
    _load_execution_snapshot,
    _matches_snapshot as _matches_execution_snapshot,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_path_cutover_models import (
    EvidenceRecoveryReadPathCutoverAuthorization,
    EvidenceRecoveryReadPathCutoverAuthorizationReceipt,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

READ_PATH_CUTOVER_AUTHORIZATION_WINDOW = timedelta(minutes=10)


class RecoveryReadPathCutoverAuthorizationError(RuntimeError):
    pass


class RecoveryReadPathCutoverAuthorizationNotFound(RecoveryReadPathCutoverAuthorizationError):
    pass


class RecoveryReadPathCutoverAuthorizationConflict(RecoveryReadPathCutoverAuthorizationError):
    pass


class RecoveryReadPathCutoverAuthorizationUnavailable(RecoveryReadPathCutoverAuthorizationError):
    pass


@dataclass(frozen=True)
class ReadPathCutoverAuthorizationSnapshot:
    execution_lease_id: UUID
    execution_activation_receipt_id: UUID
    execution_rollback_receipt_id: UUID
    cutover_admission_id: UUID
    admission_approval_receipt_id: UUID
    authority_switch_rehearsal_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    lease_hash: str
    execution_snapshot_hash: str
    execution_activation_receipt_hash: str
    execution_rollback_receipt_hash: str
    execution_transition_proof_hash: str
    admission_hash: str
    admission_approval_receipt_hash: str
    rehearsal_contract_hash: str
    rehearsal_lineage_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    request_snapshot_hash: str
    execution_activated_by_id: UUID
    parent_expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _execution_receipt(
    db: Session,
    *,
    lease: EvidenceRecoveryCutoverExecutionLease,
    phase: str,
) -> EvidenceRecoveryCutoverExecutionReceipt:
    receipt = db.scalar(
        select(EvidenceRecoveryCutoverExecutionReceipt)
        .where(
            EvidenceRecoveryCutoverExecutionReceipt.organization_id == lease.organization_id,
            EvidenceRecoveryCutoverExecutionReceipt.claim_id == lease.claim_id,
            EvidenceRecoveryCutoverExecutionReceipt.document_id == lease.document_id,
            EvidenceRecoveryCutoverExecutionReceipt.execution_lease_id == lease.id,
            EvidenceRecoveryCutoverExecutionReceipt.phase == phase,
        )
        .order_by(
            EvidenceRecoveryCutoverExecutionReceipt.transitioned_at.desc(),
            EvidenceRecoveryCutoverExecutionReceipt.created_at.desc(),
            EvidenceRecoveryCutoverExecutionReceipt.id.desc(),
        )
        .limit(1)
    )
    if receipt is None:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            f"Recovery cutover execution lease has no {phase} receipt"
        )
    if not all(
        (
            receipt.cutover_admission_id == lease.cutover_admission_id,
            receipt.admission_hash == lease.admission_hash,
            receipt.admission_approval_receipt_hash == lease.admission_approval_receipt_hash,
            receipt.execution_snapshot_hash == lease.execution_snapshot_hash,
            receipt.lease_hash == lease.lease_hash,
            receipt.read_path_switched is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
        )
    ):
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Recovery cutover execution receipt lineage is inconsistent"
        )
    return receipt


def _load_authorization_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_lease_id: UUID,
    now: datetime | None = None,
) -> ReadPathCutoverAuthorizationSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        lease = _get_lease(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=execution_lease_id,
        )
        if lease.status != "rolled_back":
            raise RecoveryReadPathCutoverAuthorizationConflict(
                "Only a successfully rolled-back cutover execution lease can request read-path authorization"
            )
        if lease.activated_by_id is None or lease.activated_at is None:
            raise RecoveryReadPathCutoverAuthorizationConflict(
                "Recovery cutover execution lease has no activation lineage"
            )
        if lease.rolled_back_by_id is None or lease.rolled_back_at is None:
            raise RecoveryReadPathCutoverAuthorizationConflict(
                "Recovery cutover execution lease has no rollback lineage"
            )
        if any(
            (
                lease.read_path_switched,
                lease.document_storage_key_mutated,
                lease.active_backend_changed,
                lease.authoritative_storage_changed,
                lease.destructive_action_performed,
                lease.s3_delete_performed,
                lease.local_delete_performed,
            )
        ):
            raise RecoveryReadPathCutoverAuthorizationConflict(
                "Recovery cutover execution lease crossed its non-routable safety boundary"
            )

        execution_snapshot = _load_execution_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=lease.cutover_admission_id,
            now=current_time,
        )
        if not _matches_execution_snapshot(lease, execution_snapshot):
            raise RecoveryReadPathCutoverAuthorizationConflict(
                "Recovery cutover execution lease lineage drifted before read-path authorization"
            )

        activation = _execution_receipt(db, lease=lease, phase="activated")
        rollback = _execution_receipt(db, lease=lease, phase="rolled_back")
        if not all(
            (
                activation.from_state == "prepared",
                activation.to_state == "activated",
                rollback.from_state == "activated",
                rollback.to_state == "rolled_back",
                activation.actor_id == lease.activated_by_id,
                rollback.actor_id == lease.rolled_back_by_id,
                _as_utc(activation.transitioned_at) == _as_utc(lease.activated_at),
                _as_utc(rollback.transitioned_at) == _as_utc(lease.rolled_back_at),
            )
        ):
            raise RecoveryReadPathCutoverAuthorizationConflict(
                "Recovery cutover execution transition proof is inconsistent"
            )

        execution_transition_proof_hash = _canonical_hash(
            {
                "execution_lease_id": str(lease.id),
                "lease_hash": lease.lease_hash,
                "execution_snapshot_hash": lease.execution_snapshot_hash,
                "activation_receipt_id": str(activation.id),
                "activation_receipt_hash": activation.receipt_hash,
                "rollback_receipt_id": str(rollback.id),
                "rollback_receipt_hash": rollback.receipt_hash,
                "source_authority_fingerprint": lease.source_authority_fingerprint,
                "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
                "rollback_verified": True,
                "read_path_switched": False,
                "authoritative_storage_changed": False,
            }
        )
        request_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "execution_lease_id": str(lease.id),
                "cutover_admission_id": str(lease.cutover_admission_id),
                "admission_approval_receipt_id": str(lease.admission_approval_receipt_id),
                "authority_switch_rehearsal_id": str(lease.authority_switch_rehearsal_id),
                "shadow_promotion_id": str(lease.shadow_promotion_id),
                "attestation_id": str(lease.attestation_id),
                "replica_id": str(lease.replica_id),
                "restore_rehearsal_id": str(lease.restore_rehearsal_id),
                "restore_verification_id": str(lease.restore_verification_id),
                "shadow_verification_id": str(lease.shadow_verification_id),
                "lease_hash": lease.lease_hash,
                "execution_snapshot_hash": lease.execution_snapshot_hash,
                "execution_transition_proof_hash": execution_transition_proof_hash,
                "admission_hash": lease.admission_hash,
                "admission_approval_receipt_hash": lease.admission_approval_receipt_hash,
                "rehearsal_contract_hash": lease.rehearsal_contract_hash,
                "rehearsal_lineage_hash": lease.rehearsal_lineage_hash,
                "source_authority_fingerprint": lease.source_authority_fingerprint,
                "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
                "configuration_fingerprint": lease.configuration_fingerprint,
                "mode": "production_read_path_cutover_authorization_only",
                "routable_authority_created": False,
                "read_path_switched": False,
            }
        )
        return ReadPathCutoverAuthorizationSnapshot(
            execution_lease_id=lease.id,
            execution_activation_receipt_id=activation.id,
            execution_rollback_receipt_id=rollback.id,
            cutover_admission_id=lease.cutover_admission_id,
            admission_approval_receipt_id=lease.admission_approval_receipt_id,
            authority_switch_rehearsal_id=lease.authority_switch_rehearsal_id,
            shadow_promotion_id=lease.shadow_promotion_id,
            attestation_id=lease.attestation_id,
            replica_id=lease.replica_id,
            restore_rehearsal_id=lease.restore_rehearsal_id,
            restore_verification_id=lease.restore_verification_id,
            shadow_verification_id=lease.shadow_verification_id,
            lease_hash=lease.lease_hash,
            execution_snapshot_hash=lease.execution_snapshot_hash,
            execution_activation_receipt_hash=activation.receipt_hash,
            execution_rollback_receipt_hash=rollback.receipt_hash,
            execution_transition_proof_hash=execution_transition_proof_hash,
            admission_hash=lease.admission_hash,
            admission_approval_receipt_hash=lease.admission_approval_receipt_hash,
            rehearsal_contract_hash=lease.rehearsal_contract_hash,
            rehearsal_lineage_hash=lease.rehearsal_lineage_hash,
            source_authority_fingerprint=lease.source_authority_fingerprint,
            candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
            configuration_fingerprint=lease.configuration_fingerprint,
            request_snapshot_hash=request_snapshot_hash,
            execution_activated_by_id=lease.activated_by_id,
            parent_expires_at=min(
                _as_utc(execution_snapshot.admission_expires_at),
                _as_utc(execution_snapshot.attestation_expires_at),
            ),
        )
    except RecoveryReadPathCutoverAuthorizationError:
        raise
    except RecoveryCutoverExecutionNotFound as exc:
        raise RecoveryReadPathCutoverAuthorizationNotFound(str(exc)) from exc
    except RecoveryCutoverExecutionConflict as exc:
        raise RecoveryReadPathCutoverAuthorizationConflict(str(exc)) from exc
    except RecoveryCutoverExecutionUnavailable as exc:
        raise RecoveryReadPathCutoverAuthorizationUnavailable(str(exc)) from exc


def _matches_snapshot(
    authorization: EvidenceRecoveryReadPathCutoverAuthorization,
    snapshot: ReadPathCutoverAuthorizationSnapshot,
) -> bool:
    return all(
        (
            authorization.execution_lease_id == snapshot.execution_lease_id,
            authorization.execution_activation_receipt_id == snapshot.execution_activation_receipt_id,
            authorization.execution_rollback_receipt_id == snapshot.execution_rollback_receipt_id,
            authorization.cutover_admission_id == snapshot.cutover_admission_id,
            authorization.admission_approval_receipt_id == snapshot.admission_approval_receipt_id,
            authorization.authority_switch_rehearsal_id == snapshot.authority_switch_rehearsal_id,
            authorization.shadow_promotion_id == snapshot.shadow_promotion_id,
            authorization.attestation_id == snapshot.attestation_id,
            authorization.replica_id == snapshot.replica_id,
            authorization.restore_rehearsal_id == snapshot.restore_rehearsal_id,
            authorization.restore_verification_id == snapshot.restore_verification_id,
            authorization.shadow_verification_id == snapshot.shadow_verification_id,
            authorization.lease_hash == snapshot.lease_hash,
            authorization.execution_snapshot_hash == snapshot.execution_snapshot_hash,
            authorization.execution_activation_receipt_hash == snapshot.execution_activation_receipt_hash,
            authorization.execution_rollback_receipt_hash == snapshot.execution_rollback_receipt_hash,
            authorization.execution_transition_proof_hash == snapshot.execution_transition_proof_hash,
            authorization.admission_hash == snapshot.admission_hash,
            authorization.admission_approval_receipt_hash == snapshot.admission_approval_receipt_hash,
            authorization.rehearsal_contract_hash == snapshot.rehearsal_contract_hash,
            authorization.rehearsal_lineage_hash == snapshot.rehearsal_lineage_hash,
            authorization.source_authority_fingerprint == snapshot.source_authority_fingerprint,
            authorization.candidate_authority_fingerprint == snapshot.candidate_authority_fingerprint,
            authorization.configuration_fingerprint == snapshot.configuration_fingerprint,
            authorization.request_snapshot_hash == snapshot.request_snapshot_hash,
            authorization.execution_activated_by_id == snapshot.execution_activated_by_id,
        )
    )


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryReadPathCutoverAuthorization:
    stmt = select(EvidenceRecoveryReadPathCutoverAuthorization).where(
        EvidenceRecoveryReadPathCutoverAuthorization.id == authorization_id,
        EvidenceRecoveryReadPathCutoverAuthorization.organization_id == organization_id,
        EvidenceRecoveryReadPathCutoverAuthorization.claim_id == claim_id,
        EvidenceRecoveryReadPathCutoverAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    item = db.scalar(stmt)
    if item is None:
        raise RecoveryReadPathCutoverAuthorizationNotFound(
            "Recovery read-path cutover authorization not found"
        )
    return item


def _new_receipt(
    *,
    authorization: EvidenceRecoveryReadPathCutoverAuthorization,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryReadPathCutoverAuthorizationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "execution_lease_id": str(authorization.execution_lease_id),
            "phase": phase,
            "request_snapshot_hash": authorization.request_snapshot_hash,
            "authorization_hash": authorization.authorization_hash,
            "execution_transition_proof_hash": authorization.execution_transition_proof_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": False,
            "read_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    return EvidenceRecoveryReadPathCutoverAuthorizationReceipt(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        authorization_id=authorization.id,
        execution_lease_id=authorization.execution_lease_id,
        phase=phase,
        request_snapshot_hash=authorization.request_snapshot_hash,
        authorization_hash=authorization.authorization_hash,
        execution_transition_proof_hash=authorization.execution_transition_proof_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=False,
        read_path_switched=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
    )


def _terminalize(
    db: Session,
    *,
    authorization: EvidenceRecoveryReadPathCutoverAuthorization,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryReadPathCutoverAuthorizationReceipt:
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


def request_recovery_read_path_cutover_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_lease_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadPathCutoverAuthorization,
    EvidenceRecoveryReadPathCutoverAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Read-path cutover authorization request reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_authorization_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_lease_id=execution_lease_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryReadPathCutoverAuthorization)
        .where(
            EvidenceRecoveryReadPathCutoverAuthorization.organization_id == organization_id,
            EvidenceRecoveryReadPathCutoverAuthorization.claim_id == claim_id,
            EvidenceRecoveryReadPathCutoverAuthorization.document_id == document_id,
            EvidenceRecoveryReadPathCutoverAuthorization.execution_lease_id == execution_lease_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if _matches_snapshot(existing, snapshot) and existing.status in {
            "pending_second_approval",
            "approved",
        }:
            return existing, None, "unchanged"
        if existing.status == "pending_second_approval":
            receipt = _terminalize(
                db,
                authorization=existing,
                status="invalidated",
                actor_id=requested_by_id,
                reason="Read-path cutover authorization lineage drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "A terminal read-path cutover authorization already exists for this execution lease"
        )

    expires_at = min(
        current_time + READ_PATH_CUTOVER_AUTHORIZATION_WINDOW,
        _as_utc(snapshot.parent_expires_at),
    )
    if expires_at <= current_time:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Read-path cutover authorization approval window is not available"
        )
    authorization_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "execution_lease_id": str(execution_lease_id),
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "execution_transition_proof_hash": snapshot.execution_transition_proof_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "authorization_expires_at": _utc_iso(expires_at),
            "mode": "approval_evidence_only",
            "routable_authority_created": False,
            "read_path_switched": False,
        }
    )
    authorization = EvidenceRecoveryReadPathCutoverAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_lease_id=snapshot.execution_lease_id,
        execution_activation_receipt_id=snapshot.execution_activation_receipt_id,
        execution_rollback_receipt_id=snapshot.execution_rollback_receipt_id,
        cutover_admission_id=snapshot.cutover_admission_id,
        admission_approval_receipt_id=snapshot.admission_approval_receipt_id,
        authority_switch_rehearsal_id=snapshot.authority_switch_rehearsal_id,
        shadow_promotion_id=snapshot.shadow_promotion_id,
        attestation_id=snapshot.attestation_id,
        replica_id=snapshot.replica_id,
        restore_rehearsal_id=snapshot.restore_rehearsal_id,
        restore_verification_id=snapshot.restore_verification_id,
        shadow_verification_id=snapshot.shadow_verification_id,
        lease_hash=snapshot.lease_hash,
        execution_snapshot_hash=snapshot.execution_snapshot_hash,
        execution_activation_receipt_hash=snapshot.execution_activation_receipt_hash,
        execution_rollback_receipt_hash=snapshot.execution_rollback_receipt_hash,
        execution_transition_proof_hash=snapshot.execution_transition_proof_hash,
        admission_hash=snapshot.admission_hash,
        admission_approval_receipt_hash=snapshot.admission_approval_receipt_hash,
        rehearsal_contract_hash=snapshot.rehearsal_contract_hash,
        rehearsal_lineage_hash=snapshot.rehearsal_lineage_hash,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        authorization_hash=authorization_hash,
        status="pending_second_approval",
        authorization_expires_at=expires_at,
        execution_activated_by_id=snapshot.execution_activated_by_id,
        requested_by_id=requested_by_id,
        requested_at=current_time,
        request_reason=normalized_reason,
        routable_authority_created=False,
        read_path_switched=False,
        document_storage_key_mutated=False,
        active_backend_changed=False,
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
    return authorization, receipt, "requested"


def approve_recovery_read_path_cutover_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadPathCutoverAuthorization,
    EvidenceRecoveryReadPathCutoverAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Read-path cutover authorization approval reason is required"
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
    if authorization.status == "approved":
        return authorization, None, "unchanged"
    if authorization.status != "pending_second_approval":
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Only a pending read-path cutover authorization can be approved"
        )
    if authorization.requested_by_id == approved_by_id:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Read-path cutover authorization requires approval by a different Admin"
        )
    if authorization.execution_activated_by_id == approved_by_id:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Read-path cutover authorization approver must differ from the execution lease activator"
        )
    if current_time >= _as_utc(authorization.authorization_expires_at):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="expired",
            actor_id=approved_by_id,
            reason="Read-path cutover authorization approval window expired",
            now=current_time,
        )
        return authorization, receipt, "expired"
    try:
        snapshot = _load_authorization_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_lease_id=authorization.execution_lease_id,
            now=current_time,
        )
    except (
        RecoveryReadPathCutoverAuthorizationConflict,
        RecoveryReadPathCutoverAuthorizationNotFound,
    ) as exc:
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh read-path cutover authorization preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return authorization, receipt, "invalidated"
    if not _matches_snapshot(authorization, snapshot):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Read-path cutover authorization lineage drifted before approval",
            now=current_time,
        )
        return authorization, receipt, "invalidated"

    authorization.status = "approved"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current_time
    authorization.approval_reason = normalized_reason
    receipt = _new_receipt(
        authorization=authorization,
        phase="approved",
        actor_id=approved_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "approved"


def reject_recovery_read_path_cutover_authorization(
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
    EvidenceRecoveryReadPathCutoverAuthorization,
    EvidenceRecoveryReadPathCutoverAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Read-path cutover authorization rejection reason is required"
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
        return authorization, None, "unchanged"
    if authorization.status != "pending_second_approval":
        raise RecoveryReadPathCutoverAuthorizationConflict(
            "Only a pending read-path cutover authorization can be rejected"
        )
    authorization.status = "rejected"
    authorization.rejected_by_id = rejected_by_id
    authorization.rejected_at = current_time
    authorization.rejection_reason = normalized_reason
    authorization.terminal_by_id = rejected_by_id
    authorization.terminal_at = current_time
    authorization.terminal_reason = normalized_reason
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


def get_recovery_read_path_cutover_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> EvidenceRecoveryReadPathCutoverAuthorization:
    return _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )


def list_recovery_read_path_cutover_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> list[EvidenceRecoveryReadPathCutoverAuthorizationReceipt]:
    _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryReadPathCutoverAuthorizationReceipt)
            .where(
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.organization_id == organization_id,
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.claim_id == claim_id,
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.document_id == document_id,
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.authorization_id == authorization_id,
            )
            .order_by(
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.created_at.asc(),
                EvidenceRecoveryReadPathCutoverAuthorizationReceipt.id.asc(),
            )
        ).all()
    )
