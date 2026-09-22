from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.external_document_sources.connection_authorization_router import router
from app.modules.external_document_sources.observation_refresh_admission_authorization_router import (
    ObservationRefreshAdmissionAdminMfa,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_schemas import (
    ExternalDocumentSourceObservationRefreshAdmissionRead,
    ExternalDocumentSourceObservationRefreshAdmissionReceiptRead,
    ExternalDocumentSourceObservationRefreshAdmissionRequest,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
    get_observation_refresh_admission_execution,
    list_observation_refresh_admission_execution_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)


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
        "/profiles/{profile_id}/evidence-family-bindings/{binding_id}"
        "/observation-refresh-admissions/{authorization_id}"
    ),
    response_model=ExternalDocumentSourceObservationRefreshAdmissionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_observation_refresh_admission_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceObservationRefreshAdmissionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdmissionAdminMfa,
) -> ExternalDocumentSourceObservationRefreshAdmissionRead:
    try:
        execution, _outcome = execute_observation_refresh_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=authorization_id,
            executed_by_id=current_user.id,
            request_key=payload.request_key,
            execution_reason=payload.reason,
        )
        return ExternalDocumentSourceObservationRefreshAdmissionRead.model_validate(
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
    (
        "/profiles/{profile_id}/observation-refresh-admissions"
        "/{execution_id}"
    ),
    response_model=ExternalDocumentSourceObservationRefreshAdmissionRead,
)
def get_observation_refresh_admission_execution_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdmissionAdminMfa,
) -> ExternalDocumentSourceObservationRefreshAdmissionRead:
    try:
        execution = get_observation_refresh_admission_execution(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceObservationRefreshAdmissionRead.model_validate(
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
    (
        "/profiles/{profile_id}/observation-refresh-admissions"
        "/{execution_id}/receipts"
    ),
    response_model=list[ExternalDocumentSourceObservationRefreshAdmissionReceiptRead],
)
def list_observation_refresh_admission_execution_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationRefreshAdmissionAdminMfa,
) -> list[ExternalDocumentSourceObservationRefreshAdmissionReceiptRead]:
    try:
        rows = list_observation_refresh_admission_execution_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceObservationRefreshAdmissionReceiptRead.model_validate(
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
