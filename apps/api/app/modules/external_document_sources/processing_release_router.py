from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import require_roles_with_mfa
from app.modules.external_document_sources.processing_release_schemas import (
    ExternalDocumentSourceProcessingReleaseRead,
    ExternalDocumentSourceProcessingReleaseReceiptRead,
    ExternalDocumentSourceProcessingReleaseRequest,
    ExternalDocumentSourceProcessingReleaseRevokeRequest,
)
from app.modules.external_document_sources.processing_release_service import (
    grant_processing_release,
    list_processing_release_receipts,
    revoke_processing_release,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.processing.router import router
from app.modules.users.models import User, UserRole

ProcessingReleaseAdminMfa = Annotated[
    User,
    Depends(require_roles_with_mfa(UserRole.ADMIN)),
]


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/release",
    response_model=ExternalDocumentSourceProcessingReleaseRead,
    status_code=status.HTTP_201_CREATED,
)
def grant_processing_release_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: ExternalDocumentSourceProcessingReleaseRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ProcessingReleaseAdminMfa,
) -> ExternalDocumentSourceProcessingReleaseRead:
    try:
        release, _outcome = grant_processing_release(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            released_by_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
        )
        return ExternalDocumentSourceProcessingReleaseRead.model_validate(release)
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
    "/release/revoke",
    response_model=ExternalDocumentSourceProcessingReleaseRead,
)
def revoke_processing_release_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: ExternalDocumentSourceProcessingReleaseRevokeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ProcessingReleaseAdminMfa,
) -> ExternalDocumentSourceProcessingReleaseRead:
    try:
        release, _outcome = revoke_processing_release(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            revoked_by_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
        )
        return ExternalDocumentSourceProcessingReleaseRead.model_validate(release)
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
    "/release/receipts",
    response_model=list[ExternalDocumentSourceProcessingReleaseReceiptRead],
)
def list_processing_release_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ProcessingReleaseAdminMfa,
) -> list[ExternalDocumentSourceProcessingReleaseReceiptRead]:
    try:
        rows = list_processing_release_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        return [
            ExternalDocumentSourceProcessingReleaseReceiptRead.model_validate(row)
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
