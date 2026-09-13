from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_physical_disposal_execution_schemas import (
    PhysicalDisposalExecutionRead,
    PhysicalDisposalExecutionReceiptRead,
    PhysicalDisposalExecutionRequest,
)
from app.modules.claims.retention_physical_disposal_execution_service import (
    PhysicalDisposalExecutionError,
    PhysicalDisposalExecutionRetryableError,
    execute_physical_disposal,
    get_physical_disposal_execution,
    list_physical_disposal_execution_receipts,
)
from app.modules.claims.retention_physical_disposal_storage import PhysicalDisposalStorageError
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter()


def _read(execution, items) -> PhysicalDisposalExecutionRead:
    payload = PhysicalDisposalExecutionRead.model_validate(execution).model_dump()
    payload["items"] = items
    return PhysicalDisposalExecutionRead.model_validate(payload)


@router.post(
    "/{claim_id}/physical-disposal-admissions/{authorization_id}/execute",
    response_model=PhysicalDisposalExecutionRead,
    status_code=status.HTTP_200_OK,
)
def execute_physical_disposal_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    payload: PhysicalDisposalExecutionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalExecutionRead:
    try:
        execution, items, outcome = execute_physical_disposal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
            request_id=payload.request_id,
            executor_id=current_user.id,
            execution_reason=payload.reason,
        )
        if outcome != "unchanged":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="PHYSICAL_DISPOSAL_EXECUTED",
                entity_type="physical_disposal_execution",
                entity_id=execution.id,
                new_values={
                    "claim_id": str(claim_id),
                    "authorization_id": str(authorization_id),
                    "request_id": str(payload.request_id),
                    "status": execution.status,
                    "document_count": execution.document_count,
                    "deleted_count": execution.deleted_count,
                    "execution_hash": execution.execution_hash,
                    "destructive_action_performed": execution.destructive_action_performed,
                    "local_delete_performed": execution.local_delete_performed,
                    "s3_delete_performed": False,
                    "recovery_bytes_preserved": execution.recovery_bytes_preserved,
                    "document_row_deleted": False,
                    "document_storage_key_mutated": False,
                },
            )
            db.commit()
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PhysicalDisposalExecutionRetryableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "physical_disposal_retryable", "message": str(exc)},
        ) from exc
    except (PhysicalDisposalExecutionError, PhysicalDisposalStorageError, IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(execution, items)


@router.get(
    "/{claim_id}/physical-disposal-executions/{execution_id}",
    response_model=PhysicalDisposalExecutionRead,
)
def get_physical_disposal_execution_endpoint(
    claim_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> PhysicalDisposalExecutionRead:
    try:
        execution, items = get_physical_disposal_execution(
            db, organization_id=current_user.organization_id, claim_id=claim_id, execution_id=execution_id
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(execution, items)


@router.get(
    "/{claim_id}/physical-disposal-executions/{execution_id}/receipts",
    response_model=list[PhysicalDisposalExecutionReceiptRead],
)
def list_physical_disposal_execution_receipts_endpoint(
    claim_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[PhysicalDisposalExecutionReceiptRead]:
    try:
        receipts = list_physical_disposal_execution_receipts(
            db, organization_id=current_user.organization_id, claim_id=claim_id, execution_id=execution_id
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [PhysicalDisposalExecutionReceiptRead.model_validate(receipt) for receipt in receipts]
