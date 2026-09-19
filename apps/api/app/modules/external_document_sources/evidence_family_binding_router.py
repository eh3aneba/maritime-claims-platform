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
from app.modules.external_document_sources.evidence_family_binding_schemas import (
    ExternalDocumentSourceEvidenceFamilyBindingRead,
    ExternalDocumentSourceEvidenceFamilyBindingReceiptRead,
    ExternalDocumentSourceEvidenceFamilyBindingRequest,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    bind_external_document_source_evidence_family,
    get_external_document_source_evidence_family_binding,
    list_external_document_source_evidence_family_binding_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/profiles/{profile_id}/evidence-admission-executions/{execution_id}/family-binding",
    response_model=ExternalDocumentSourceEvidenceFamilyBindingRead,
    status_code=status.HTTP_201_CREATED,
)
def bind_evidence_family_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    payload: ExternalDocumentSourceEvidenceFamilyBindingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceEvidenceFamilyBindingRead:
    try:
        binding, _outcome = bind_external_document_source_evidence_family(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            admission_execution_id=execution_id,
            bound_by_id=current_user.id,
            request_key=payload.request_key,
            binding_reason=payload.reason,
        )
        return ExternalDocumentSourceEvidenceFamilyBindingRead.model_validate(binding)
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
    "/profiles/{profile_id}/evidence-family-bindings/{binding_id}",
    response_model=ExternalDocumentSourceEvidenceFamilyBindingRead,
)
def get_evidence_family_binding_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceEvidenceFamilyBindingRead:
    try:
        binding = get_external_document_source_evidence_family_binding(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
        )
        return ExternalDocumentSourceEvidenceFamilyBindingRead.model_validate(binding)
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
    "/profiles/{profile_id}/evidence-family-bindings/{binding_id}/receipts",
    response_model=list[ExternalDocumentSourceEvidenceFamilyBindingReceiptRead],
)
def list_evidence_family_binding_receipts_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceEvidenceFamilyBindingReceiptRead]:
    try:
        rows = list_external_document_source_evidence_family_binding_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
        )
        return [
            ExternalDocumentSourceEvidenceFamilyBindingReceiptRead.model_validate(row)
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
