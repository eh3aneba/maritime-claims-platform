from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentAuthContext, enforce_current_mfa_for_context
from app.modules.external_document_sources.connection_authorization_router import router
from app.modules.external_document_sources.observation_refresh_execution_schemas import (
    ExternalDocumentSourceObservationRefreshExecuteRequest,
    ExternalDocumentSourceObservationRefreshExecutionRead,
    ExternalDocumentSourceObservationRefreshReceiptRead,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
    get_observation_refresh_execution,
    list_observation_refresh_execution_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User, UserRole


def require_observation_refresh_admin_current_mfa(
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


ObservationRefreshAdminMfa = Annotated[
    User,
    Depends(require_observation_refresh_admin_current_mfa),
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
    "/profiles/{profile_id}/observation-refresh-authorizations/{authorization_id}/execute",
    response_model=ExternalDocumentSourceObservationRefreshExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_observation_refresh_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceObservationRefreshExecuteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdminMfa,
) -> ExternalDocumentSourceObservationRefreshExecutionRead:
    try:
        execution, _outcome = execute_observation_refresh_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        return ExternalDocumentSourceObservationRefreshExecutionRead.model_validate(
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
    "/profiles/{profile_id}/observation-refresh-executions/{execution_id}",
    response_model=ExternalDocumentSourceObservationRefreshExecutionRead,
)
def get_observation_refresh_execution_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdminMfa,
) -> ExternalDocumentSourceObservationRefreshExecutionRead:
    try:
        execution = get_observation_refresh_execution(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceObservationRefreshExecutionRead.model_validate(
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
    "/profiles/{profile_id}/observation-refresh-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceObservationRefreshReceiptRead],
)
def list_observation_refresh_execution_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdminMfa,
) -> list[ExternalDocumentSourceObservationRefreshReceiptRead]:
    try:
        rows = list_observation_refresh_execution_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceObservationRefreshReceiptRead.model_validate(row)
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
