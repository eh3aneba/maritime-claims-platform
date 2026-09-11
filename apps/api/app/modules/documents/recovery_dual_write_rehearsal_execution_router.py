from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_dual_write_rehearsal_execution_schemas import (
    RecoveryDualWriteRehearsalExecutionOperationRead,
    RecoveryDualWriteRehearsalExecutionRead,
    RecoveryDualWriteRehearsalExecutionReason,
    RecoveryDualWriteRehearsalExecutionReceiptRead,
)
from app.modules.documents.recovery_dual_write_rehearsal_execution_service import (
    RecoveryDualWriteRehearsalExecutionConflict,
    RecoveryDualWriteRehearsalExecutionNotFound,
    RecoveryDualWriteRehearsalExecutionUnavailable,
    execute_dual_write_rehearsal,
    get_dual_write_rehearsal_execution,
    list_dual_write_rehearsal_execution_receipts,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-dual-write-rehearsal-execution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDualWriteRehearsalExecutionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDualWriteRehearsalExecutionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(execution) -> dict:
    return {
        "claim_id": str(execution.claim_id),
        "document_id": str(execution.document_id),
        "phase_x_authorization_id": str(execution.phase_x_authorization_id),
        "phase_x_approval_receipt_id": str(execution.phase_x_approval_receipt_id),
        "phase_w_health_qualification_id": str(execution.phase_w_health_qualification_id),
        "phase_v_transition_lease_id": str(execution.phase_v_transition_lease_id),
        "phase_u_authorization_id": str(execution.phase_u_authorization_id),
        "phase_t_health_qualification_id": str(execution.phase_t_health_qualification_id),
        "replica_id": str(execution.replica_id),
        "phase_x_authorization_hash": execution.phase_x_authorization_hash,
        "phase_x_approval_receipt_hash": execution.phase_x_approval_receipt_hash,
        "source_file_hash": execution.source_file_hash,
        "source_file_size_bytes": execution.source_file_size_bytes,
        "rehearsal_object_key_fingerprint": execution.rehearsal_object_key_fingerprint,
        "verification_hash": execution.verification_hash,
        "execution_hash": execution.execution_hash,
        "route_version_at_execution": execution.route_version_at_execution,
        "conditional_write_performed": execution.conditional_write_performed,
        "max_rehearsal_writes": execution.max_rehearsal_writes,
        "status": execution.status,
        "rehearsal_executed": True,
        "rehearsal_write_verified": True,
        "rehearsal_object_routable": False,
        "dual_write_active": False,
        "durable_write_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(execution, receipt, outcome: str):
    return RecoveryDualWriteRehearsalExecutionOperationRead(
        execution=RecoveryDualWriteRehearsalExecutionRead.model_validate(execution),
        receipt=RecoveryDualWriteRehearsalExecutionReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-authorizations/{authorization_id}/execute",
    response_model=RecoveryDualWriteRehearsalExecutionOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_dual_write_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDualWriteRehearsalExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        execution, receipt, outcome = execute_dual_write_rehearsal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            executed_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "executed": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_EXECUTED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_EXECUTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_execution",
            entity_id=execution.id,
            new_values={**_audit_values(execution), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        db.commit()
        db.refresh(execution)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryDualWriteRehearsalExecutionNotFound,
        RecoveryDualWriteRehearsalExecutionConflict,
        RecoveryDualWriteRehearsalExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase Y execution conflicts with immutable lineage") from exc
    return _operation(execution, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-executions/{execution_id}",
    response_model=RecoveryDualWriteRehearsalExecutionRead,
)
def get_dual_write_rehearsal_execution_endpoint(
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        execution = get_dual_write_rehearsal_execution(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_id=execution_id,
        )
    except RecoveryDualWriteRehearsalExecutionNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDualWriteRehearsalExecutionRead.model_validate(execution)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-executions/{execution_id}/receipts",
    response_model=list[RecoveryDualWriteRehearsalExecutionReceiptRead],
)
def list_dual_write_rehearsal_execution_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_dual_write_rehearsal_execution_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_id=execution_id,
        )
    except (
        RecoveryDualWriteRehearsalExecutionNotFound,
        RecoveryDualWriteRehearsalExecutionConflict,
    ) as exc:
        raise _error(exc) from exc
    return [RecoveryDualWriteRehearsalExecutionReceiptRead.model_validate(item) for item in receipts]
