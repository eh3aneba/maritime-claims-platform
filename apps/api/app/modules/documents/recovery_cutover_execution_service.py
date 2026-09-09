from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_cutover_admission_models import (
    EvidenceRecoveryCutoverAdmission,
    EvidenceRecoveryCutoverAdmissionReceipt,
)
from app.modules.documents.recovery_cutover_admission_service import (
    RecoveryCutoverAdmissionConflict,
    RecoveryCutoverAdmissionNotFound,
    RecoveryCutoverAdmissionUnavailable,
    _get_admission,
    _load_admission_snapshot,
    _matches_snapshot as _matches_admission_snapshot,
)
from app.modules.documents.recovery_cutover_execution_models import (
    EvidenceRecoveryCutoverExecutionLease,
    EvidenceRecoveryCutoverExecutionReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

CUTOVER_EXECUTION_LEASE_WINDOW = timedelta(minutes=10)


class RecoveryCutoverExecutionError(RuntimeError):
    pass


class RecoveryCutoverExecutionNotFound(RecoveryCutoverExecutionError):
    pass


class RecoveryCutoverExecutionConflict(RecoveryCutoverExecutionError):
    pass


class RecoveryCutoverExecutionUnavailable(RecoveryCutoverExecutionError):
    pass


@dataclass(frozen=True)
class CutoverExecutionSnapshot:
    admission_id: UUID
    admission_approval_receipt_id: UUID
    authority_switch_rehearsal_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    admission_hash: str
    admission_request_snapshot_hash: str
    admission_approval_receipt_hash: str
    transition_proof_hash: str
    rehearsal_contract_hash: str
    rehearsal_lineage_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    execution_snapshot_hash: str
    admission_approved_by_id: UUID
    admission_expires_at: datetime
    attestation_expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approval_receipt(
    db: Session, admission: EvidenceRecoveryCutoverAdmission
) -> EvidenceRecoveryCutoverAdmissionReceipt:
    receipt = db.scalar(
        select(EvidenceRecoveryCutoverAdmissionReceipt)
        .where(
            EvidenceRecoveryCutoverAdmissionReceipt.organization_id == admission.organization_id,
            EvidenceRecoveryCutoverAdmissionReceipt.claim_id == admission.claim_id,
            EvidenceRecoveryCutoverAdmissionReceipt.document_id == admission.document_id,
            EvidenceRecoveryCutoverAdmissionReceipt.cutover_admission_id == admission.id,
            EvidenceRecoveryCutoverAdmissionReceipt.phase == "approved",
        )
        .order_by(
            EvidenceRecoveryCutoverAdmissionReceipt.transitioned_at.desc(),
            EvidenceRecoveryCutoverAdmissionReceipt.created_at.desc(),
            EvidenceRecoveryCutoverAdmissionReceipt.id.desc(),
        )
        .limit(1)
    )
    if receipt is None:
        raise RecoveryCutoverExecutionConflict("Approved cutover admission has no approval receipt")
    if (
        receipt.admission_hash != admission.admission_hash
        or receipt.request_snapshot_hash != admission.request_snapshot_hash
        or receipt.transition_proof_hash != admission.transition_proof_hash
        or receipt.execution_authority_created
    ):
        raise RecoveryCutoverExecutionConflict("Cutover admission approval receipt lineage is inconsistent")
    return receipt


def _load_execution_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    now: datetime | None = None,
) -> CutoverExecutionSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        admission = _get_admission(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=admission_id,
        )
        if admission.status != "approved" or admission.approved_by_id is None or admission.approved_at is None:
            raise RecoveryCutoverExecutionConflict("Only an approved cutover admission can prepare an execution lease")
        if current_time >= _as_utc(admission.admission_expires_at):
            raise RecoveryCutoverExecutionConflict("Approved cutover admission is outside its bounded execution window")
        if any(
            (
                admission.cutover_performed,
                admission.authoritative_storage_changed,
                admission.document_storage_key_mutated,
                admission.active_backend_changed,
                admission.production_execution_token_created,
                admission.execution_authority_created,
            )
        ):
            raise RecoveryCutoverExecutionConflict("Cutover admission crossed the non-executable safety boundary")

        admission_snapshot = _load_admission_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=admission.authority_switch_rehearsal_id,
            now=current_time,
        )
        if not _matches_admission_snapshot(admission, admission_snapshot):
            raise RecoveryCutoverExecutionConflict("Cutover admission lineage drifted before execution lease")
        approval = _approval_receipt(db, admission)

        execution_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "cutover_admission_id": str(admission.id),
                "admission_hash": admission.admission_hash,
                "admission_request_snapshot_hash": admission.request_snapshot_hash,
                "admission_approval_receipt_id": str(approval.id),
                "admission_approval_receipt_hash": approval.receipt_hash,
                "authority_switch_rehearsal_id": str(admission.authority_switch_rehearsal_id),
                "transition_proof_hash": admission.transition_proof_hash,
                "rehearsal_contract_hash": admission.rehearsal_contract_hash,
                "rehearsal_lineage_hash": admission.rehearsal_lineage_hash,
                "source_authority_fingerprint": admission.source_authority_fingerprint,
                "candidate_authority_fingerprint": admission.candidate_authority_fingerprint,
                "configuration_fingerprint": admission.configuration_fingerprint,
                "mode": "bounded_non_routable_cutover_execution_lease",
                "read_path_switched": False,
                "authoritative_storage_changed": False,
            }
        )
        return CutoverExecutionSnapshot(
            admission_id=admission.id,
            admission_approval_receipt_id=approval.id,
            authority_switch_rehearsal_id=admission.authority_switch_rehearsal_id,
            shadow_promotion_id=admission.shadow_promotion_id,
            attestation_id=admission.attestation_id,
            replica_id=admission.replica_id,
            restore_rehearsal_id=admission.restore_rehearsal_id,
            restore_verification_id=admission.restore_verification_id,
            shadow_verification_id=admission.shadow_verification_id,
            admission_hash=admission.admission_hash,
            admission_request_snapshot_hash=admission.request_snapshot_hash,
            admission_approval_receipt_hash=approval.receipt_hash,
            transition_proof_hash=admission.transition_proof_hash,
            rehearsal_contract_hash=admission.rehearsal_contract_hash,
            rehearsal_lineage_hash=admission.rehearsal_lineage_hash,
            source_authority_fingerprint=admission.source_authority_fingerprint,
            candidate_authority_fingerprint=admission.candidate_authority_fingerprint,
            configuration_fingerprint=admission.configuration_fingerprint,
            execution_snapshot_hash=execution_snapshot_hash,
            admission_approved_by_id=admission.approved_by_id,
            admission_expires_at=_as_utc(admission.admission_expires_at),
            attestation_expires_at=_as_utc(admission_snapshot.attestation_expires_at),
        )
    except RecoveryCutoverExecutionError:
        raise
    except RecoveryCutoverAdmissionNotFound as exc:
        raise RecoveryCutoverExecutionNotFound(str(exc)) from exc
    except RecoveryCutoverAdmissionConflict as exc:
        raise RecoveryCutoverExecutionConflict(str(exc)) from exc
    except RecoveryCutoverAdmissionUnavailable as exc:
        raise RecoveryCutoverExecutionUnavailable(str(exc)) from exc


def _matches_snapshot(
    lease: EvidenceRecoveryCutoverExecutionLease,
    snapshot: CutoverExecutionSnapshot,
) -> bool:
    return all(
        (
            lease.cutover_admission_id == snapshot.admission_id,
            lease.admission_approval_receipt_id == snapshot.admission_approval_receipt_id,
            lease.authority_switch_rehearsal_id == snapshot.authority_switch_rehearsal_id,
            lease.shadow_promotion_id == snapshot.shadow_promotion_id,
            lease.attestation_id == snapshot.attestation_id,
            lease.replica_id == snapshot.replica_id,
            lease.restore_rehearsal_id == snapshot.restore_rehearsal_id,
            lease.restore_verification_id == snapshot.restore_verification_id,
            lease.shadow_verification_id == snapshot.shadow_verification_id,
            lease.admission_hash == snapshot.admission_hash,
            lease.admission_request_snapshot_hash == snapshot.admission_request_snapshot_hash,
            lease.admission_approval_receipt_hash == snapshot.admission_approval_receipt_hash,
            lease.transition_proof_hash == snapshot.transition_proof_hash,
            lease.rehearsal_contract_hash == snapshot.rehearsal_contract_hash,
            lease.rehearsal_lineage_hash == snapshot.rehearsal_lineage_hash,
            lease.source_authority_fingerprint == snapshot.source_authority_fingerprint,
            lease.candidate_authority_fingerprint == snapshot.candidate_authority_fingerprint,
            lease.configuration_fingerprint == snapshot.configuration_fingerprint,
            lease.execution_snapshot_hash == snapshot.execution_snapshot_hash,
            lease.admission_approved_by_id == snapshot.admission_approved_by_id,
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
) -> EvidenceRecoveryCutoverExecutionLease:
    stmt = select(EvidenceRecoveryCutoverExecutionLease).where(
        EvidenceRecoveryCutoverExecutionLease.id == lease_id,
        EvidenceRecoveryCutoverExecutionLease.organization_id == organization_id,
        EvidenceRecoveryCutoverExecutionLease.claim_id == claim_id,
        EvidenceRecoveryCutoverExecutionLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    item = db.scalar(stmt)
    if item is None:
        raise RecoveryCutoverExecutionNotFound("Recovery cutover execution lease not found")
    return item


def _new_receipt(
    *,
    lease: EvidenceRecoveryCutoverExecutionLease,
    phase: str,
    from_state: str,
    to_state: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryCutoverExecutionReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "execution_lease_id": str(lease.id),
            "cutover_admission_id": str(lease.cutover_admission_id),
            "phase": phase,
            "from_state": from_state,
            "to_state": to_state,
            "admission_hash": lease.admission_hash,
            "admission_approval_receipt_hash": lease.admission_approval_receipt_hash,
            "execution_snapshot_hash": lease.execution_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "read_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    return EvidenceRecoveryCutoverExecutionReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        execution_lease_id=lease.id,
        cutover_admission_id=lease.cutover_admission_id,
        phase=phase,
        from_state=from_state,
        to_state=to_state,
        admission_hash=lease.admission_hash,
        admission_approval_receipt_hash=lease.admission_approval_receipt_hash,
        execution_snapshot_hash=lease.execution_snapshot_hash,
        lease_hash=lease.lease_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        read_path_switched=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
    )


def _terminalize(
    db: Session,
    *,
    lease: EvidenceRecoveryCutoverExecutionLease,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryCutoverExecutionReceipt:
    previous = lease.status
    lease.status = status
    lease.terminal_by_id = actor_id
    lease.terminal_at = now
    lease.terminal_reason = reason
    receipt = _new_receipt(
        lease=lease,
        phase=status,
        from_state=previous,
        to_state=status,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def prepare_recovery_cutover_execution_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryCutoverExecutionLease, EvidenceRecoveryCutoverExecutionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryCutoverExecutionConflict("Cutover execution lease preparation reason is required")
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_execution_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        admission_id=admission_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryCutoverExecutionLease)
        .where(
            EvidenceRecoveryCutoverExecutionLease.organization_id == organization_id,
            EvidenceRecoveryCutoverExecutionLease.claim_id == claim_id,
            EvidenceRecoveryCutoverExecutionLease.document_id == document_id,
            EvidenceRecoveryCutoverExecutionLease.cutover_admission_id == admission_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if _matches_snapshot(existing, snapshot) and existing.status in {"prepared", "activated", "rolled_back"}:
            return existing, None, "unchanged"
        if existing.status == "prepared":
            receipt = _terminalize(
                db,
                lease=existing,
                status="invalidated",
                actor_id=prepared_by_id,
                reason="Cutover execution lease lineage drifted before preparation replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        raise RecoveryCutoverExecutionConflict("A terminal cutover execution lease already exists for this admission")

    expires_at = min(
        current_time + CUTOVER_EXECUTION_LEASE_WINDOW,
        snapshot.admission_expires_at,
        snapshot.attestation_expires_at,
    )
    if expires_at <= current_time:
        raise RecoveryCutoverExecutionConflict("Cutover execution lease window is not available")
    lease_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "cutover_admission_id": str(admission_id),
            "execution_snapshot_hash": snapshot.execution_snapshot_hash,
            "prepared_by_id": str(prepared_by_id),
            "prepared_at": _utc_iso(current_time),
            "lease_expires_at": _utc_iso(expires_at),
            "mode": "non_routable_execution_lease",
            "read_path_switched": False,
        }
    )
    lease = EvidenceRecoveryCutoverExecutionLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        cutover_admission_id=snapshot.admission_id,
        admission_approval_receipt_id=snapshot.admission_approval_receipt_id,
        authority_switch_rehearsal_id=snapshot.authority_switch_rehearsal_id,
        shadow_promotion_id=snapshot.shadow_promotion_id,
        attestation_id=snapshot.attestation_id,
        replica_id=snapshot.replica_id,
        restore_rehearsal_id=snapshot.restore_rehearsal_id,
        restore_verification_id=snapshot.restore_verification_id,
        shadow_verification_id=snapshot.shadow_verification_id,
        admission_hash=snapshot.admission_hash,
        admission_request_snapshot_hash=snapshot.admission_request_snapshot_hash,
        admission_approval_receipt_hash=snapshot.admission_approval_receipt_hash,
        transition_proof_hash=snapshot.transition_proof_hash,
        rehearsal_contract_hash=snapshot.rehearsal_contract_hash,
        rehearsal_lineage_hash=snapshot.rehearsal_lineage_hash,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        execution_snapshot_hash=snapshot.execution_snapshot_hash,
        lease_hash=lease_hash,
        status="prepared",
        lease_expires_at=expires_at,
        admission_approved_by_id=snapshot.admission_approved_by_id,
        prepared_by_id=prepared_by_id,
        prepared_at=current_time,
        preparation_reason=normalized_reason,
        read_path_switched=False,
        document_storage_key_mutated=False,
        active_backend_changed=False,
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
        from_state="none",
        to_state="prepared",
        actor_id=prepared_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, receipt, "prepared"


def activate_recovery_cutover_execution_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryCutoverExecutionLease, EvidenceRecoveryCutoverExecutionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryCutoverExecutionConflict("Cutover execution activation reason is required")
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status == "activated":
        return lease, None, "unchanged"
    if lease.status != "prepared":
        raise RecoveryCutoverExecutionConflict("Only a prepared cutover execution lease can be activated")
    if lease.prepared_by_id == activated_by_id:
        raise RecoveryCutoverExecutionConflict("Execution activation requires a different Admin from the preparer")
    if lease.admission_approved_by_id == activated_by_id:
        raise RecoveryCutoverExecutionConflict("Execution activator must differ from the cutover admission approver")
    if current_time >= _as_utc(lease.lease_expires_at):
        receipt = _terminalize(
            db,
            lease=lease,
            status="expired",
            actor_id=activated_by_id,
            reason="Cutover execution lease activation window expired",
            now=current_time,
        )
        return lease, receipt, "expired"
    try:
        snapshot = _load_execution_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=lease.cutover_admission_id,
            now=current_time,
        )
    except (RecoveryCutoverExecutionConflict, RecoveryCutoverExecutionNotFound) as exc:
        receipt = _terminalize(
            db,
            lease=lease,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh cutover execution preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return lease, receipt, "invalidated"
    if not _matches_snapshot(lease, snapshot):
        receipt = _terminalize(
            db,
            lease=lease,
            status="invalidated",
            actor_id=activated_by_id,
            reason="Cutover execution lease lineage drifted before activation",
            now=current_time,
        )
        return lease, receipt, "invalidated"

    lease.status = "activated"
    lease.activated_by_id = activated_by_id
    lease.activated_at = current_time
    lease.activation_reason = normalized_reason
    receipt = _new_receipt(
        lease=lease,
        phase="activated",
        from_state="prepared",
        to_state="activated",
        actor_id=activated_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, receipt, "activated"


def rollback_recovery_cutover_execution_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryCutoverExecutionLease, EvidenceRecoveryCutoverExecutionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryCutoverExecutionConflict("Cutover execution rollback reason is required")
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status == "rolled_back":
        return lease, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryCutoverExecutionConflict("Only an activated cutover execution lease can be rolled back")

    lease.status = "rolled_back"
    lease.rolled_back_by_id = rolled_back_by_id
    lease.rolled_back_at = current_time
    lease.rollback_reason = normalized_reason
    receipt = _new_receipt(
        lease=lease,
        phase="rolled_back",
        from_state="activated",
        to_state="rolled_back",
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, receipt, "rolled_back"


def get_recovery_cutover_execution_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryCutoverExecutionLease:
    return _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )


def list_recovery_cutover_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> list[EvidenceRecoveryCutoverExecutionReceipt]:
    _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryCutoverExecutionReceipt)
            .where(
                EvidenceRecoveryCutoverExecutionReceipt.organization_id == organization_id,
                EvidenceRecoveryCutoverExecutionReceipt.claim_id == claim_id,
                EvidenceRecoveryCutoverExecutionReceipt.document_id == document_id,
                EvidenceRecoveryCutoverExecutionReceipt.execution_lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryCutoverExecutionReceipt.transitioned_at.asc(),
                EvidenceRecoveryCutoverExecutionReceipt.created_at.asc(),
                EvidenceRecoveryCutoverExecutionReceipt.id.asc(),
            )
        ).all()
    )
