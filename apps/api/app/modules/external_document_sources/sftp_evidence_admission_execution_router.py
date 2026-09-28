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
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_schemas import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead,
    ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceiptRead,
    ExternalDocumentSourceSftpEvidenceAdmissionExecutionRequest,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_service import (
    execute_external_document_source_sftp_evidence_admission,
    get_external_document_source_sftp_evidence_admission_execution,
    list_external_document_source_sftp_evidence_admission_execution_receipts,
)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/profiles/{profile_id}/sftp-evidence-admission-authorizations/{authorization_id}/executions",
    response_model=ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_evidence_admission_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceSftpEvidenceAdmissionExecutionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead:
    try:
        execution, _outcome = execute_external_document_source_sftp_evidence_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            executed_by_id=current_user.id,
            request_key=payload.request_key,
            execution_reason=payload.reason,
            document_type=payload.document_type,
            confidentiality_level=payload.confidentiality_level,
        )
        return ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead.model_validate(
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
    "/profiles/{profile_id}/sftp-evidence-admission-executions/{execution_id}",
    response_model=ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead,
)
def get_sftp_evidence_admission_execution_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead:
    try:
        execution = get_external_document_source_sftp_evidence_admission_execution(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceSftpEvidenceAdmissionExecutionRead.model_validate(
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
    "/profiles/{profile_id}/sftp-evidence-admission-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceiptRead],
)
def list_sftp_evidence_admission_execution_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceiptRead]:
    try:
        rows = list_external_document_source_sftp_evidence_admission_execution_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceiptRead.model_validate(row)
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
