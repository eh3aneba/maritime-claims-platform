from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authority_switch_models import (
    EvidenceRecoveryAuthoritySwitchReceipt,
    EvidenceRecoveryAuthoritySwitchRehearsal,
)
from app.modules.documents.recovery_authority_switch_service import (
    RecoveryAuthoritySwitchConflict,
    RecoveryAuthoritySwitchNotFound,
    RecoveryAuthoritySwitchUnavailable,
    _get_rehearsal,
    _load_switch_snapshot,
    _matches_snapshot as _matches_switch_snapshot,
)
from app.modules.documents.recovery_cutover_admission_models import (
    EvidenceRecoveryCutoverAdmission,
    EvidenceRecoveryCutoverAdmissionReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso

CUTOVER_ADMISSION_WINDOW = timedelta(minutes=15)


class RecoveryCutoverAdmissionError(RuntimeError):
    pass


class RecoveryCutoverAdmissionNotFound(RecoveryCutoverAdmissionError):
    pass


class RecoveryCutoverAdmissionConflict(RecoveryCutoverAdmissionError):
    pass


class RecoveryCutoverAdmissionUnavailable(RecoveryCutoverAdmissionError):
    pass


@dataclass(frozen=True)
class CutoverAdmissionSnapshot:
    rehearsal_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    rehearsal_contract_hash: str
    rehearsal_lineage_hash: str
    activation_receipt_id: UUID
    activation_receipt_hash: str
    rollback_receipt_id: UUID
    rollback_receipt_hash: str
    transition_proof_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    request_snapshot_hash: str
    attestation_expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _transition_receipt(
    db: Session,
    *,
    rehearsal: EvidenceRecoveryAuthoritySwitchRehearsal,
    phase: str,
) -> EvidenceRecoveryAuthoritySwitchReceipt:
    receipt = db.scalar(
        select(EvidenceRecoveryAuthoritySwitchReceipt)
        .where(
            EvidenceRecoveryAuthoritySwitchReceipt.organization_id == rehearsal.organization_id,
            EvidenceRecoveryAuthoritySwitchReceipt.claim_id == rehearsal.claim_id,
            EvidenceRecoveryAuthoritySwitchReceipt.document_id == rehearsal.document_id,
            EvidenceRecoveryAuthoritySwitchReceipt.authority_switch_rehearsal_id == rehearsal.id,
            EvidenceRecoveryAuthoritySwitchReceipt.phase == phase,
        )
        .order_by(
            EvidenceRecoveryAuthoritySwitchReceipt.transitioned_at.desc(),
            EvidenceRecoveryAuthoritySwitchReceipt.created_at.desc(),
            EvidenceRecoveryAuthoritySwitchReceipt.id.desc(),
        )
        .limit(1)
    )
    if receipt is None:
        raise RecoveryCutoverAdmissionConflict(f"Authority-switch rehearsal has no {phase} receipt")
    if receipt.contract_hash != rehearsal.contract_hash or receipt.lineage_hash != rehearsal.lineage_hash:
        raise RecoveryCutoverAdmissionConflict("Authority-switch receipt lineage does not match the rehearsal")
    return receipt


def _load_admission_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    now: datetime | None = None,
) -> CutoverAdmissionSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        rehearsal = _get_rehearsal(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal_id,
        )
        if rehearsal.status != "rolled_back":
            raise RecoveryCutoverAdmissionConflict("Only a successfully rolled-back authority-switch rehearsal can be admitted")
        if rehearsal.activated_by_id is None or rehearsal.activated_at is None:
            raise RecoveryCutoverAdmissionConflict("Authority-switch rehearsal has no activation lineage")
        if rehearsal.rolled_back_by_id is None or rehearsal.rolled_back_at is None:
            raise RecoveryCutoverAdmissionConflict("Authority-switch rehearsal has no rollback lineage")
        if rehearsal.virtual_authority_class != "authoritative_source":
            raise RecoveryCutoverAdmissionConflict("Authority-switch rehearsal did not return to authoritative source")
        if rehearsal.virtual_authority_fingerprint != rehearsal.source_authority_fingerprint:
            raise RecoveryCutoverAdmissionConflict("Authority-switch rollback fingerprint does not match source authority")
        if any(
            (
                rehearsal.cutover_performed,
                rehearsal.authoritative_storage_changed,
                rehearsal.document_storage_key_mutated,
                rehearsal.active_backend_changed,
            )
        ):
            raise RecoveryCutoverAdmissionConflict("Authority-switch rehearsal crossed the no-cutover safety boundary")

        switch_snapshot = _load_switch_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            shadow_promotion_id=rehearsal.shadow_promotion_id,
            now=current_time,
        )
        if not _matches_switch_snapshot(rehearsal, switch_snapshot):
            raise RecoveryCutoverAdmissionConflict("Authority-switch rehearsal lineage drifted")

        activation = _transition_receipt(db, rehearsal=rehearsal, phase="activated")
        rollback = _transition_receipt(db, rehearsal=rehearsal, phase="rolled_back")
        if not all(
            (
                activation.from_authority_class == "authoritative_source",
                activation.to_authority_class == "recovery_shadow_candidate",
                activation.from_authority_fingerprint == rehearsal.source_authority_fingerprint,
                activation.to_authority_fingerprint == rehearsal.candidate_authority_fingerprint,
                rollback.from_authority_class == "recovery_shadow_candidate",
                rollback.to_authority_class == "authoritative_source",
                rollback.from_authority_fingerprint == rehearsal.candidate_authority_fingerprint,
                rollback.to_authority_fingerprint == rehearsal.source_authority_fingerprint,
                activation.cutover_performed is False,
                rollback.cutover_performed is False,
                activation.authoritative_storage_changed is False,
                rollback.authoritative_storage_changed is False,
            )
        ):
            raise RecoveryCutoverAdmissionConflict("Authority-switch transition proof is inconsistent")

        transition_proof_hash = _canonical_hash(
            {
                "authority_switch_rehearsal_id": str(rehearsal.id),
                "rehearsal_contract_hash": rehearsal.contract_hash,
                "rehearsal_lineage_hash": rehearsal.lineage_hash,
                "activation_receipt_id": str(activation.id),
                "activation_receipt_hash": activation.receipt_hash,
                "rollback_receipt_id": str(rollback.id),
                "rollback_receipt_hash": rollback.receipt_hash,
                "source_authority_fingerprint": rehearsal.source_authority_fingerprint,
                "candidate_authority_fingerprint": rehearsal.candidate_authority_fingerprint,
                "rollback_verified": True,
            }
        )
        request_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "authority_switch_rehearsal_id": str(rehearsal.id),
                "shadow_promotion_id": str(rehearsal.shadow_promotion_id),
                "attestation_id": str(rehearsal.attestation_id),
                "replica_id": str(rehearsal.replica_id),
                "restore_rehearsal_id": str(rehearsal.restore_rehearsal_id),
                "restore_verification_id": str(rehearsal.restore_verification_id),
                "shadow_verification_id": str(rehearsal.shadow_verification_id),
                "rehearsal_contract_hash": rehearsal.contract_hash,
                "rehearsal_lineage_hash": rehearsal.lineage_hash,
                "transition_proof_hash": transition_proof_hash,
                "configuration_fingerprint": rehearsal.configuration_fingerprint,
                "source_authority_fingerprint": rehearsal.source_authority_fingerprint,
                "candidate_authority_fingerprint": rehearsal.candidate_authority_fingerprint,
                "mode": "governed_cutover_admission_only",
                "execution_authority_created": False,
            }
        )
        return CutoverAdmissionSnapshot(
            rehearsal_id=rehearsal.id,
            shadow_promotion_id=rehearsal.shadow_promotion_id,
            attestation_id=rehearsal.attestation_id,
            replica_id=rehearsal.replica_id,
            restore_rehearsal_id=rehearsal.restore_rehearsal_id,
            restore_verification_id=rehearsal.restore_verification_id,
            shadow_verification_id=rehearsal.shadow_verification_id,
            rehearsal_contract_hash=rehearsal.contract_hash,
            rehearsal_lineage_hash=rehearsal.lineage_hash,
            activation_receipt_id=activation.id,
            activation_receipt_hash=activation.receipt_hash,
            rollback_receipt_id=rollback.id,
            rollback_receipt_hash=rollback.receipt_hash,
            transition_proof_hash=transition_proof_hash,
            source_authority_fingerprint=rehearsal.source_authority_fingerprint,
            candidate_authority_fingerprint=rehearsal.candidate_authority_fingerprint,
            configuration_fingerprint=rehearsal.configuration_fingerprint,
            request_snapshot_hash=request_snapshot_hash,
            attestation_expires_at=switch_snapshot.attestation_expires_at,
        )
    except RecoveryCutoverAdmissionError:
        raise
    except RecoveryAuthoritySwitchNotFound as exc:
        raise RecoveryCutoverAdmissionNotFound(str(exc)) from exc
    except RecoveryAuthoritySwitchConflict as exc:
        raise RecoveryCutoverAdmissionConflict(str(exc)) from exc
    except RecoveryAuthoritySwitchUnavailable as exc:
        raise RecoveryCutoverAdmissionUnavailable(str(exc)) from exc


def _matches_snapshot(admission: EvidenceRecoveryCutoverAdmission, snapshot: CutoverAdmissionSnapshot) -> bool:
    return all(
        (
            admission.authority_switch_rehearsal_id == snapshot.rehearsal_id,
            admission.activation_receipt_id == snapshot.activation_receipt_id,
            admission.rollback_receipt_id == snapshot.rollback_receipt_id,
            admission.shadow_promotion_id == snapshot.shadow_promotion_id,
            admission.attestation_id == snapshot.attestation_id,
            admission.replica_id == snapshot.replica_id,
            admission.restore_rehearsal_id == snapshot.restore_rehearsal_id,
            admission.restore_verification_id == snapshot.restore_verification_id,
            admission.shadow_verification_id == snapshot.shadow_verification_id,
            admission.rehearsal_contract_hash == snapshot.rehearsal_contract_hash,
            admission.rehearsal_lineage_hash == snapshot.rehearsal_lineage_hash,
            admission.activation_receipt_hash == snapshot.activation_receipt_hash,
            admission.rollback_receipt_hash == snapshot.rollback_receipt_hash,
            admission.transition_proof_hash == snapshot.transition_proof_hash,
            admission.source_authority_fingerprint == snapshot.source_authority_fingerprint,
            admission.candidate_authority_fingerprint == snapshot.candidate_authority_fingerprint,
            admission.configuration_fingerprint == snapshot.configuration_fingerprint,
            admission.request_snapshot_hash == snapshot.request_snapshot_hash,
        )
    )


def _get_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryCutoverAdmission:
    stmt = select(EvidenceRecoveryCutoverAdmission).where(
        EvidenceRecoveryCutoverAdmission.id == admission_id,
        EvidenceRecoveryCutoverAdmission.organization_id == organization_id,
        EvidenceRecoveryCutoverAdmission.claim_id == claim_id,
        EvidenceRecoveryCutoverAdmission.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    item = db.scalar(stmt)
    if item is None:
        raise RecoveryCutoverAdmissionNotFound("Recovery cutover admission not found")
    return item


def _new_receipt(
    *,
    admission: EvidenceRecoveryCutoverAdmission,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryCutoverAdmissionReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "cutover_admission_id": str(admission.id),
            "authority_switch_rehearsal_id": str(admission.authority_switch_rehearsal_id),
            "phase": phase,
            "request_snapshot_hash": admission.request_snapshot_hash,
            "admission_hash": admission.admission_hash,
            "transition_proof_hash": admission.transition_proof_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "execution_authority_created": False,
        }
    )
    return EvidenceRecoveryCutoverAdmissionReceipt(
        organization_id=admission.organization_id,
        claim_id=admission.claim_id,
        document_id=admission.document_id,
        cutover_admission_id=admission.id,
        authority_switch_rehearsal_id=admission.authority_switch_rehearsal_id,
        phase=phase,
        request_snapshot_hash=admission.request_snapshot_hash,
        admission_hash=admission.admission_hash,
        transition_proof_hash=admission.transition_proof_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        execution_authority_created=False,
    )


def _terminalize(
    db: Session,
    *,
    admission: EvidenceRecoveryCutoverAdmission,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryCutoverAdmissionReceipt:
    admission.status = status
    admission.terminal_by_id = actor_id
    admission.terminal_at = now
    admission.terminal_reason = reason
    receipt = _new_receipt(
        admission=admission,
        phase=status,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_recovery_cutover_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryCutoverAdmission, EvidenceRecoveryCutoverAdmissionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryCutoverAdmissionConflict("Cutover admission request reason is required")
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_admission_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        rehearsal_id=rehearsal_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryCutoverAdmission)
        .where(
            EvidenceRecoveryCutoverAdmission.organization_id == organization_id,
            EvidenceRecoveryCutoverAdmission.claim_id == claim_id,
            EvidenceRecoveryCutoverAdmission.document_id == document_id,
            EvidenceRecoveryCutoverAdmission.authority_switch_rehearsal_id == rehearsal_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if _matches_snapshot(existing, snapshot) and existing.status in {"pending_second_approval", "approved"}:
            return existing, None, "unchanged"
        if existing.status == "pending_second_approval":
            receipt = _terminalize(
                db,
                admission=existing,
                status="invalidated",
                actor_id=requested_by_id,
                reason="Cutover admission lineage drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        raise RecoveryCutoverAdmissionConflict("A terminal cutover admission already exists for this rehearsal")

    expires_at = min(current_time + CUTOVER_ADMISSION_WINDOW, _as_utc(snapshot.attestation_expires_at))
    if expires_at <= current_time:
        raise RecoveryCutoverAdmissionConflict("Cutover admission approval window is not available")
    admission_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "authority_switch_rehearsal_id": str(rehearsal_id),
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "transition_proof_hash": snapshot.transition_proof_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "admission_expires_at": _utc_iso(expires_at),
            "mode": "approval_evidence_only",
            "production_execution_token_created": False,
            "execution_authority_created": False,
        }
    )
    admission = EvidenceRecoveryCutoverAdmission(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authority_switch_rehearsal_id=snapshot.rehearsal_id,
        activation_receipt_id=snapshot.activation_receipt_id,
        rollback_receipt_id=snapshot.rollback_receipt_id,
        shadow_promotion_id=snapshot.shadow_promotion_id,
        attestation_id=snapshot.attestation_id,
        replica_id=snapshot.replica_id,
        restore_rehearsal_id=snapshot.restore_rehearsal_id,
        restore_verification_id=snapshot.restore_verification_id,
        shadow_verification_id=snapshot.shadow_verification_id,
        rehearsal_contract_hash=snapshot.rehearsal_contract_hash,
        rehearsal_lineage_hash=snapshot.rehearsal_lineage_hash,
        activation_receipt_hash=snapshot.activation_receipt_hash,
        rollback_receipt_hash=snapshot.rollback_receipt_hash,
        transition_proof_hash=snapshot.transition_proof_hash,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        admission_hash=admission_hash,
        status="pending_second_approval",
        admission_expires_at=expires_at,
        requested_by_id=requested_by_id,
        requested_at=current_time,
        request_reason=normalized_reason,
        cutover_performed=False,
        authoritative_storage_changed=False,
        document_storage_key_mutated=False,
        active_backend_changed=False,
        production_execution_token_created=False,
        execution_authority_created=False,
    )
    db.add(admission)
    db.flush()
    receipt = _new_receipt(
        admission=admission,
        phase="requested",
        actor_id=requested_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return admission, receipt, "requested"


def approve_recovery_cutover_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryCutoverAdmission, EvidenceRecoveryCutoverAdmissionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryCutoverAdmissionConflict("Cutover admission approval reason is required")
    current_time = _as_utc(now or _utc_now())
    admission = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        admission_id=admission_id,
        for_update=True,
    )
    if admission.status == "approved":
        return admission, None, "unchanged"
    if admission.status != "pending_second_approval":
        raise RecoveryCutoverAdmissionConflict("Only a pending cutover admission can be approved")
    if admission.requested_by_id == approved_by_id:
        raise RecoveryCutoverAdmissionConflict("Cutover admission requires approval by a different Admin")
    if current_time >= _as_utc(admission.admission_expires_at):
        receipt = _terminalize(
            db,
            admission=admission,
            status="expired",
            actor_id=approved_by_id,
            reason="Cutover admission approval window expired",
            now=current_time,
        )
        return admission, receipt, "expired"
    try:
        snapshot = _load_admission_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=admission.authority_switch_rehearsal_id,
            now=current_time,
        )
    except (RecoveryCutoverAdmissionConflict, RecoveryCutoverAdmissionNotFound) as exc:
        receipt = _terminalize(
            db,
            admission=admission,
            status="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh cutover admission preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return admission, receipt, "invalidated"
    if not _matches_snapshot(admission, snapshot):
        receipt = _terminalize(
            db,
            admission=admission,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Cutover admission lineage drifted before approval",
            now=current_time,
        )
        return admission, receipt, "invalidated"

    admission.status = "approved"
    admission.approved_by_id = approved_by_id
    admission.approved_at = current_time
    admission.approval_reason = normalized_reason
    receipt = _new_receipt(
        admission=admission,
        phase="approved",
        actor_id=approved_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return admission, receipt, "approved"


def reject_recovery_cutover_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryCutoverAdmission, EvidenceRecoveryCutoverAdmissionReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryCutoverAdmissionConflict("Cutover admission rejection reason is required")
    current_time = _as_utc(now or _utc_now())
    admission = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        admission_id=admission_id,
        for_update=True,
    )
    if admission.status == "rejected":
        return admission, None, "unchanged"
    if admission.status != "pending_second_approval":
        raise RecoveryCutoverAdmissionConflict("Only a pending cutover admission can be rejected")
    admission.status = "rejected"
    admission.rejected_by_id = rejected_by_id
    admission.rejected_at = current_time
    admission.rejection_reason = normalized_reason
    admission.terminal_by_id = rejected_by_id
    admission.terminal_at = current_time
    admission.terminal_reason = normalized_reason
    receipt = _new_receipt(
        admission=admission,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return admission, receipt, "rejected"


def get_recovery_cutover_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
) -> EvidenceRecoveryCutoverAdmission:
    return _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        admission_id=admission_id,
    )


def list_recovery_cutover_admission_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
) -> list[EvidenceRecoveryCutoverAdmissionReceipt]:
    _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        admission_id=admission_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryCutoverAdmissionReceipt)
            .where(
                EvidenceRecoveryCutoverAdmissionReceipt.organization_id == organization_id,
                EvidenceRecoveryCutoverAdmissionReceipt.claim_id == claim_id,
                EvidenceRecoveryCutoverAdmissionReceipt.document_id == document_id,
                EvidenceRecoveryCutoverAdmissionReceipt.cutover_admission_id == admission_id,
            )
            .order_by(
                EvidenceRecoveryCutoverAdmissionReceipt.transitioned_at.asc(),
                EvidenceRecoveryCutoverAdmissionReceipt.created_at.asc(),
                EvidenceRecoveryCutoverAdmissionReceipt.id.asc(),
            )
        ).all()
    )
