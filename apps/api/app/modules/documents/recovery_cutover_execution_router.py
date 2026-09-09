from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_cutover_execution_schemas import (
    RecoveryCutoverExecutionLeaseRead,
    RecoveryCutoverExecutionOperationRead,
    RecoveryCutoverExecutionReason,
    RecoveryCutoverExecutionReceiptRead,
)
from app.modules.documents.recovery_cutover_execution_service import (
    RecoveryCutoverExecutionConflict,
    RecoveryCutoverExecutionNotFound,
    RecoveryCutoverExecutionUnavailable,
    activate_recovery_cutover_execution_lease,
    get_recovery_cutover_execution_lease,
    list_recovery_cutover_execution_receipts,
    prepare_recovery_cutover_execution_lease,
    rollback_recovery_cutover_execution_lease,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-cutover-execution"])


def _audit_values(lease) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "cutover_admission_id": str(lease.cutover_admission_id),
        "admission_approval_receipt_id": str(lease.admission_approval_receipt_id),
        "authority_switch_rehearsal_id": str(lease.authority_switch_rehearsal_id),
        "shadow_promotion_id": str(lease.shadow_promotion_id),
        "attestation_id": str(lease.attestation_id),
        "replica_id": str(lease.replica_id),
        "restore_rehearsal_id": str(lease.restore_rehearsal_id),
        "restore_verification_id": str(lease.restore_verification_id),
        "shadow_verification_id": str(lease.shadow_verification_id),
        "admission_hash": lease.admission_hash,
        "admission_approval_receipt_hash": lease.admission_approval_receipt_hash,
        "execution_snapshot_hash": lease.execution_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "source_authority_fingerprint": lease.source_authority_fingerprint,
        "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
        "configuration_fingerprint": lease.configuration_fingerprint,
        "status": lease.status,
        "read_path_switched": False,
        "document_storage_key_mutated": False,
        "active_backend_changed": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryCutoverExecutionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryCutoverExecutionConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryCutoverExecutionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery cutover execution conflict")


def _operation_read(lease, receipt, outcome: str) -> RecoveryCutoverExecutionOperationRead:
    return RecoveryCutoverExecutionOperationRead(
        lease=RecoveryCutoverExecutionLeaseRead.model_validate(lease),
        receipt=(RecoveryCutoverExecutionReceiptRead.model_validate(receipt) if receipt is not None else None),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/execution-lease",
    response_model=RecoveryCutoverExecutionOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_cutover_execution_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    admission_id: UUID,
    payload: RecoveryCutoverExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryCutoverExecutionOperationRead:
    try:
        lease, receipt, outcome = prepare_recovery_cutover_execution_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            admission_id=admission_id,
            prepared_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "prepared": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_PREPARED",
                "unchanged": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_PREPARE_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_cutover_execution_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(lease)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryCutoverExecutionNotFound, RecoveryCutoverExecutionConflict, RecoveryCutoverExecutionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cutover execution lease conflicts with immutable lineage") from exc
    return _operation_read(lease, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}",
    response_model=RecoveryCutoverExecutionLeaseRead,
)
def get_cutover_execution_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryCutoverExecutionLeaseRead:
    try:
        lease = get_recovery_cutover_execution_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryCutoverExecutionNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryCutoverExecutionLeaseRead.model_validate(lease)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/activate",
    response_model=RecoveryCutoverExecutionOperationRead,
)
def activate_cutover_execution_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryCutoverExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryCutoverExecutionOperationRead:
    try:
        lease, receipt, outcome = activate_recovery_cutover_execution_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "activated": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_ACTIVATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_cutover_execution_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(lease)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryCutoverExecutionNotFound, RecoveryCutoverExecutionConflict, RecoveryCutoverExecutionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(lease, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/rollback",
    response_model=RecoveryCutoverExecutionOperationRead,
)
def rollback_cutover_execution_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryCutoverExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryCutoverExecutionOperationRead:
    try:
        lease, receipt, outcome = rollback_recovery_cutover_execution_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            rolled_back_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rolled_back": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_cutover_execution_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(lease)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryCutoverExecutionNotFound, RecoveryCutoverExecutionConflict, RecoveryCutoverExecutionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(lease, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/receipts",
    response_model=list[RecoveryCutoverExecutionReceiptRead],
)
def list_cutover_execution_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryCutoverExecutionReceiptRead]:
    try:
        receipts = list_recovery_cutover_execution_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryCutoverExecutionNotFound as exc:
        raise _operation_error(exc) from exc
    return [RecoveryCutoverExecutionReceiptRead.model_validate(item) for item in receipts]
