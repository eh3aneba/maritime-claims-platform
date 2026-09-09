from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_cutover_admission_schemas import (
    RecoveryCutoverAdmissionOperationRead,
    RecoveryCutoverAdmissionRead,
    RecoveryCutoverAdmissionReason,
    RecoveryCutoverAdmissionReceiptRead,
)
from app.modules.documents.recovery_cutover_admission_service import (
    RecoveryCutoverAdmissionConflict,
    RecoveryCutoverAdmissionNotFound,
    RecoveryCutoverAdmissionUnavailable,
    approve_recovery_cutover_admission,
    get_recovery_cutover_admission,
    list_recovery_cutover_admission_receipts,
    reject_recovery_cutover_admission,
    request_recovery_cutover_admission,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-cutover-admission"])


def _audit_values(admission) -> dict:
    return {
        "claim_id": str(admission.claim_id),
        "document_id": str(admission.document_id),
        "authority_switch_rehearsal_id": str(admission.authority_switch_rehearsal_id),
        "activation_receipt_id": str(admission.activation_receipt_id),
        "rollback_receipt_id": str(admission.rollback_receipt_id),
        "shadow_promotion_id": str(admission.shadow_promotion_id),
        "attestation_id": str(admission.attestation_id),
        "replica_id": str(admission.replica_id),
        "restore_rehearsal_id": str(admission.restore_rehearsal_id),
        "restore_verification_id": str(admission.restore_verification_id),
        "shadow_verification_id": str(admission.shadow_verification_id),
        "rehearsal_contract_hash": admission.rehearsal_contract_hash,
        "rehearsal_lineage_hash": admission.rehearsal_lineage_hash,
        "activation_receipt_hash": admission.activation_receipt_hash,
        "rollback_receipt_hash": admission.rollback_receipt_hash,
        "transition_proof_hash": admission.transition_proof_hash,
        "source_authority_fingerprint": admission.source_authority_fingerprint,
        "candidate_authority_fingerprint": admission.candidate_authority_fingerprint,
        "configuration_fingerprint": admission.configuration_fingerprint,
        "request_snapshot_hash": admission.request_snapshot_hash,
        "admission_hash": admission.admission_hash,
        "status": admission.status,
        "cutover_performed": False,
        "authoritative_storage_changed": False,
        "document_storage_key_mutated": False,
        "active_backend_changed": False,
        "destructive_action_performed": False,
        "production_execution_token_created": False,
        "execution_authority_created": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryCutoverAdmissionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryCutoverAdmissionConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryCutoverAdmissionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery cutover admission conflict")


def _operation_read(admission, receipt, outcome: str) -> RecoveryCutoverAdmissionOperationRead:
    return RecoveryCutoverAdmissionOperationRead(
        admission=RecoveryCutoverAdmissionRead.model_validate(admission),
        receipt=(RecoveryCutoverAdmissionReceiptRead.model_validate(receipt) if receipt is not None else None),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/cutover-admission",
    response_model=RecoveryCutoverAdmissionOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_cutover_admission_endpoint(
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    payload: RecoveryCutoverAdmissionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryCutoverAdmissionOperationRead:
    try:
        admission, receipt, outcome = request_recovery_cutover_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "requested": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_REQUEST_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_cutover_admission",
            entity_id=admission.id,
            new_values={**_audit_values(admission), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(admission)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryCutoverAdmissionNotFound, RecoveryCutoverAdmissionConflict, RecoveryCutoverAdmissionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cutover admission conflicts with immutable lineage") from exc
    return _operation_read(admission, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}",
    response_model=RecoveryCutoverAdmissionRead,
)
def get_cutover_admission_endpoint(
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryCutoverAdmissionRead:
    try:
        admission = get_recovery_cutover_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=admission_id,
        )
    except RecoveryCutoverAdmissionNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryCutoverAdmissionRead.model_validate(admission)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/approve",
    response_model=RecoveryCutoverAdmissionOperationRead,
)
def approve_cutover_admission_endpoint(
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    payload: RecoveryCutoverAdmissionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryCutoverAdmissionOperationRead:
    try:
        admission, receipt, outcome = approve_recovery_cutover_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=admission_id,
            approved_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "approved": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_cutover_admission",
            entity_id=admission.id,
            new_values={**_audit_values(admission), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(admission)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryCutoverAdmissionNotFound, RecoveryCutoverAdmissionConflict, RecoveryCutoverAdmissionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(admission, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/reject",
    response_model=RecoveryCutoverAdmissionOperationRead,
)
def reject_cutover_admission_endpoint(
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    payload: RecoveryCutoverAdmissionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryCutoverAdmissionOperationRead:
    try:
        admission, receipt, outcome = reject_recovery_cutover_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=admission_id,
            rejected_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={"rejected": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_REJECTED", "unchanged": "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_REJECTION_REPLAYED"}[outcome],
            entity_type="evidence_recovery_cutover_admission",
            entity_id=admission.id,
            new_values={**_audit_values(admission), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(admission)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryCutoverAdmissionNotFound, RecoveryCutoverAdmissionConflict, RecoveryCutoverAdmissionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(admission, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/receipts",
    response_model=list[RecoveryCutoverAdmissionReceiptRead],
)
def list_cutover_admission_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryCutoverAdmissionReceiptRead]:
    try:
        receipts = list_recovery_cutover_admission_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=admission_id,
        )
    except RecoveryCutoverAdmissionNotFound as exc:
        raise _operation_error(exc) from exc
    return [RecoveryCutoverAdmissionReceiptRead.model_validate(item) for item in receipts]
