from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import (
    ConnectionAuthorizationAdminMfa,
    router,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_credential_health_schemas import (
    ExternalDocumentSourceSftpCredentialHealthRead,
    ExternalDocumentSourceSftpCredentialHealthReceiptRead,
    ExternalDocumentSourceSftpCredentialHealthRequest,
)
from app.modules.external_document_sources.sftp_credential_health_service import (
    get_external_document_source_sftp_credential_health_qualification,
    list_external_document_source_sftp_credential_health_receipts,
    qualify_external_document_source_sftp_credential_health,
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


def _audit_values(row) -> dict:
    return {
        "profile_id": str(row.profile_id),
        "credential_reference_binding_id": str(
            row.credential_reference_binding_id
        ),
        "provider_kind": "sftp",
        "authentication_kind": row.authentication_kind,
        "reference_backend": row.reference_backend,
        "locator_hash": row.locator_hash,
        "resolver_kind": row.resolver_kind,
        "scope_hash": row.scope_hash,
        "result_status": row.result_status,
        "failure_code": row.failure_code,
        "resolved_material_kind": row.resolved_material_kind,
        "result_hash": row.result_hash,
        "credential_reference_stored": True,
        "secret_resolution_performed": True,
        "credential_stored": False,
        "provider_network_performed": False,
        "authentication_performed": False,
        "sftp_session_opened": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/health-qualifications",
    response_model=ExternalDocumentSourceSftpCredentialHealthRead,
    status_code=status.HTTP_201_CREATED,
)
def qualify_sftp_credential_health_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceSftpCredentialHealthRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialHealthRead:
    try:
        row, outcome = qualify_external_document_source_sftp_credential_health(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_CREDENTIAL_HEALTH_QUALIFIED",
                entity_type="external_document_source_sftp_credential_health_qualification",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "SFTP credential-reference health qualification completed "
                    "without persisting or returning secret material and without "
                    "opening any SSH/SFTP session or remote-file authority."
                ),
            )
            db.commit()
            db.refresh(row)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceSftpCredentialHealthRead.model_validate(row)


@router.get(
    "/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}",
    response_model=ExternalDocumentSourceSftpCredentialHealthRead,
)
def get_sftp_credential_health_endpoint(
    profile_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialHealthRead:
    try:
        row = get_external_document_source_sftp_credential_health_qualification(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            qualification_id=qualification_id,
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
    return ExternalDocumentSourceSftpCredentialHealthRead.model_validate(row)


@router.get(
    "/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpCredentialHealthReceiptRead],
)
def list_sftp_credential_health_receipts_endpoint(
    profile_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpCredentialHealthReceiptRead]:
    try:
        rows = list_external_document_source_sftp_credential_health_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            qualification_id=qualification_id,
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
    return [
        ExternalDocumentSourceSftpCredentialHealthReceiptRead.model_validate(row)
        for row in rows
    ]
