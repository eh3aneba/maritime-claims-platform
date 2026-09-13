from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_physical_disposal_closure_schemas import (
    PhysicalDisposalClosureDecision,
    PhysicalDisposalClosureRead,
    PhysicalDisposalClosureReceiptRead,
    PhysicalDisposalClosureRequest,
)
from app.modules.claims.retention_physical_disposal_closure_service import (
    PhysicalDisposalClosureError,
    PhysicalDisposalClosureRetryableError,
    get_physical_disposal_closure,
    list_physical_disposal_closure_receipts,
    qualify_physical_disposal_closure,
    reject_physical_disposal_closure,
    request_physical_disposal_closure,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter()


@router.post(
    "/{claim_id}/physical-disposal-executions/{execution_id}/closure-qualification",
    response_model=PhysicalDisposalClosureRead,
    status_code=status.HTTP_201_CREATED,
)
def request_physical_disposal_closure_endpoint(
    claim_id: UUID,
    execution_id: UUID,
    payload: PhysicalDisposalClosureRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalClosureRead:
    try:
        qualification = request_physical_disposal_closure(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            execution_id=execution_id,
            requested_by_id=current_user.id,
            request_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="PHYSICAL_DISPOSAL_CLOSURE_REQUESTED",
            entity_type="physical_disposal_closure_qualification",
            entity_id=qualification.id,
            new_values={
                "claim_id": str(claim_id),
                "execution_id": str(execution_id),
                "status": qualification.status,
                "health_state": qualification.health_state,
                "execution_hash": qualification.execution_hash,
                "verification_snapshot_hash": qualification.verification_snapshot_hash,
                "closure_qualification_hash": qualification.closure_qualification_hash,
                "destructive_action_performed": False,
                "storage_write_performed": False,
                "route_mutation_performed": False,
            },
        )
        db.commit()
        db.refresh(qualification)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PhysicalDisposalClosureRetryableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "physical_disposal_closure_retryable", "message": str(exc)},
        ) from exc
    except (PhysicalDisposalClosureError, IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PhysicalDisposalClosureRead.model_validate(qualification)


@router.post(
    "/{claim_id}/physical-disposal-closures/{qualification_id}/qualify",
    response_model=PhysicalDisposalClosureRead,
)
def qualify_physical_disposal_closure_endpoint(
    claim_id: UUID,
    qualification_id: UUID,
    payload: PhysicalDisposalClosureDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalClosureRead:
    try:
        qualification, outcome = qualify_physical_disposal_closure(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            qualification_id=qualification_id,
            qualified_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action={
                    "qualified": "PHYSICAL_DISPOSAL_CLOSURE_QUALIFIED",
                    "invalidated": "PHYSICAL_DISPOSAL_CLOSURE_INVALIDATED",
                    "expired": "PHYSICAL_DISPOSAL_CLOSURE_EXPIRED",
                }[outcome],
                entity_type="physical_disposal_closure_qualification",
                entity_id=qualification.id,
                new_values={
                    "claim_id": str(claim_id),
                    "execution_id": str(qualification.execution_id),
                    "status": qualification.status,
                    "health_state": qualification.health_state,
                    "decision_hash": qualification.decision_hash,
                    "destructive_action_performed": False,
                    "storage_write_performed": False,
                    "route_mutation_performed": False,
                },
            )
            db.commit()
            db.refresh(qualification)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PhysicalDisposalClosureRetryableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "physical_disposal_closure_retryable", "message": str(exc)},
        ) from exc
    except (PhysicalDisposalClosureError, IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PhysicalDisposalClosureRead.model_validate(qualification)


@router.post(
    "/{claim_id}/physical-disposal-closures/{qualification_id}/reject",
    response_model=PhysicalDisposalClosureRead,
)
def reject_physical_disposal_closure_endpoint(
    claim_id: UUID,
    qualification_id: UUID,
    payload: PhysicalDisposalClosureDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalClosureRead:
    try:
        qualification, outcome = reject_physical_disposal_closure(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            qualification_id=qualification_id,
            rejected_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=(
                    "PHYSICAL_DISPOSAL_CLOSURE_REJECTED"
                    if outcome == "rejected"
                    else "PHYSICAL_DISPOSAL_CLOSURE_EXPIRED"
                ),
                entity_type="physical_disposal_closure_qualification",
                entity_id=qualification.id,
                new_values={
                    "claim_id": str(claim_id),
                    "execution_id": str(qualification.execution_id),
                    "status": qualification.status,
                    "destructive_action_performed": False,
                    "storage_write_performed": False,
                    "route_mutation_performed": False,
                },
            )
            db.commit()
            db.refresh(qualification)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (PhysicalDisposalClosureError, IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PhysicalDisposalClosureRead.model_validate(qualification)


@router.get(
    "/{claim_id}/physical-disposal-closures/{qualification_id}",
    response_model=PhysicalDisposalClosureRead,
)
def get_physical_disposal_closure_endpoint(
    claim_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> PhysicalDisposalClosureRead:
    try:
        qualification = get_physical_disposal_closure(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            qualification_id=qualification_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PhysicalDisposalClosureRead.model_validate(qualification)


@router.get(
    "/{claim_id}/physical-disposal-closures/{qualification_id}/receipts",
    response_model=list[PhysicalDisposalClosureReceiptRead],
)
def list_physical_disposal_closure_receipts_endpoint(
    claim_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[PhysicalDisposalClosureReceiptRead]:
    try:
        receipts = list_physical_disposal_closure_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            qualification_id=qualification_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [PhysicalDisposalClosureReceiptRead.model_validate(row) for row in receipts]
