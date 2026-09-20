from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.external_document_sources.connection_authorization_router import (
    ConnectionAuthorizationAdminMfa,
    router,
)
from app.modules.external_document_sources.family_version_admission_schemas import (
    ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead,
    ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceiptRead,
    ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRequest,
    ExternalDocumentSourceFamilyVersionAdmissionRead,
    ExternalDocumentSourceFamilyVersionAdmissionReceiptRead,
    ExternalDocumentSourceFamilyVersionAdmissionRequest,
)
from app.modules.external_document_sources.family_version_admission_service import (
    authorize_external_document_source_family_version_admission,
    execute_external_document_source_family_version_admission,
    get_external_document_source_family_version_admission,
    get_external_document_source_family_version_admission_authorization,
    list_external_document_source_family_version_admission_authorization_receipts,
    list_external_document_source_family_version_admission_receipts,
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
        "/version-admission-authorizations/{successor_versioned_restaging_execution_id}"
    ),
    response_model=ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_family_version_admission_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    successor_versioned_restaging_execution_id: UUID,
    payload: ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead:
    try:
        authorization, _outcome = (
            authorize_external_document_source_family_version_admission(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                successor_versioned_restaging_execution_id=
                    successor_versioned_restaging_execution_id,
                authorized_by_id=current_user.id,
                request_key=payload.request_key,
                authorization_reason=payload.reason,
            )
        )
        return ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead.model_validate(
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
    "/profiles/{profile_id}/evidence-family-version-admission-authorizations/{authorization_id}",
    response_model=ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead,
)
def get_family_version_admission_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead:
    try:
        authorization = (
            get_external_document_source_family_version_admission_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
        )
        return ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead.model_validate(
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
        "/profiles/{profile_id}/evidence-family-version-admission-authorizations"
        "/{authorization_id}/receipts"
    ),
    response_model=list[
        ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceiptRead
    ],
)
def list_family_version_admission_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceiptRead]:
    try:
        rows = (
            list_external_document_source_family_version_admission_authorization_receipts(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
        )
        return [
            ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceiptRead.model_validate(
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


@router.post(
    "/profiles/{profile_id}/evidence-family-bindings/{binding_id}/version-admissions/{authorization_id}",
    response_model=ExternalDocumentSourceFamilyVersionAdmissionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_family_version_admission_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceFamilyVersionAdmissionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceFamilyVersionAdmissionRead:
    try:
        execution, _outcome = execute_external_document_source_family_version_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=authorization_id,
            executed_by_id=current_user.id,
            request_key=payload.request_key,
            execution_reason=payload.reason,
        )
        return ExternalDocumentSourceFamilyVersionAdmissionRead.model_validate(
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
    "/profiles/{profile_id}/evidence-family-version-admissions/{execution_id}",
    response_model=ExternalDocumentSourceFamilyVersionAdmissionRead,
)
def get_family_version_admission_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceFamilyVersionAdmissionRead:
    try:
        execution = get_external_document_source_family_version_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceFamilyVersionAdmissionRead.model_validate(
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
    "/profiles/{profile_id}/evidence-family-version-admissions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceFamilyVersionAdmissionReceiptRead],
)
def list_family_version_admission_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceFamilyVersionAdmissionReceiptRead]:
    try:
        rows = list_external_document_source_family_version_admission_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceFamilyVersionAdmissionReceiptRead.model_validate(
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
