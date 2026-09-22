from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentAuthContext, enforce_current_mfa_for_context
from app.modules.external_document_sources.connection_authorization_router import router
from app.modules.external_document_sources.observation_refresh_admission_authorization_schemas import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead,
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceiptRead,
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRequest,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
    get_observation_refresh_admission_authorization,
    list_observation_refresh_admission_authorization_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User, UserRole


def require_observation_refresh_admission_admin_current_mfa(
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


ObservationRefreshAdmissionAdminMfa = Annotated[
    User,
    Depends(require_observation_refresh_admission_admin_current_mfa),
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
    (
        "/profiles/{profile_id}/observation-refresh-executions/{refresh_execution_id}"
        "/admission-authorizations"
    ),
    response_model=ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_observation_refresh_admission_endpoint(
    profile_id: UUID,
    refresh_execution_id: UUID,
    payload: ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdmissionAdminMfa,
) -> ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead:
    try:
        authorization, _outcome = authorize_observation_refresh_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_execution_id,
            authorized_by_id=current_user.id,
            request_key=payload.request_key,
            authorization_reason=payload.reason,
        )
        return ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead.model_validate(
            authorization
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
    (
        "/profiles/{profile_id}/observation-refresh-admission-authorizations"
        "/{authorization_id}"
    ),
    response_model=ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead,
)
def get_observation_refresh_admission_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdmissionAdminMfa,
) -> ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead:
    try:
        authorization = get_observation_refresh_admission_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        return ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead.model_validate(
            authorization
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
    (
        "/profiles/{profile_id}/observation-refresh-admission-authorizations"
        "/{authorization_id}/receipts"
    ),
    response_model=list[
        ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceiptRead
    ],
)
def list_observation_refresh_admission_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdmissionAdminMfa,
) -> list[ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceiptRead]:
    try:
        rows = list_observation_refresh_admission_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        return [
            ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceiptRead.model_validate(
                row
            )
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
