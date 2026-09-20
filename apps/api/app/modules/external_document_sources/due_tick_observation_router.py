from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import (
    CurrentAuthContext,
    enforce_current_mfa_for_context,
)
from app.modules.external_document_sources.connection_authorization_router import router
from app.modules.external_document_sources.due_tick_observation_schemas import (
    ExternalDocumentSourceDueTickObservationRead,
    ExternalDocumentSourceDueTickObservationReceiptRead,
    ExternalDocumentSourceDueTickObservationRequest,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    execute_due_tick_observation,
    get_due_tick_observation,
    list_due_tick_observation_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User, UserRole


def require_due_tick_observation_admin_current_mfa(
    context: CurrentAuthContext,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if context.user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    enforce_current_mfa_for_context(db, context=context)
    return context.user


DueTickObservationAdminMfa = Annotated[
    User,
    Depends(require_due_tick_observation_admin_current_mfa),
]


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc


@router.post(
    "/profiles/{profile_id}/recurring-observation-schedules/{schedule_id}/execute-due",
    response_model=ExternalDocumentSourceDueTickObservationRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_due_tick_observation_endpoint(
    profile_id: UUID,
    schedule_id: UUID,
    payload: ExternalDocumentSourceDueTickObservationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: DueTickObservationAdminMfa,
) -> ExternalDocumentSourceDueTickObservationRead:
    try:
        execution, _outcome = execute_due_tick_observation(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            schedule_id=schedule_id,
            executed_by_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
        )
        return ExternalDocumentSourceDueTickObservationRead.model_validate(
            execution
        )
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/due-tick-observations/{execution_id}",
    response_model=ExternalDocumentSourceDueTickObservationRead,
)
def get_due_tick_observation_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: DueTickObservationAdminMfa,
) -> ExternalDocumentSourceDueTickObservationRead:
    try:
        execution = get_due_tick_observation(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceDueTickObservationRead.model_validate(
            execution
        )
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/due-tick-observations/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceDueTickObservationReceiptRead],
)
def list_due_tick_observation_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: DueTickObservationAdminMfa,
) -> list[ExternalDocumentSourceDueTickObservationReceiptRead]:
    try:
        rows = list_due_tick_observation_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceDueTickObservationReceiptRead.model_validate(row)
            for row in rows
        ]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
