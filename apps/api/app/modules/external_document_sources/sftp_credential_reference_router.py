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
from app.modules.external_document_sources.sftp_credential_reference_schemas import (
    ExternalDocumentSourceSftpCredentialReferenceDecision,
    ExternalDocumentSourceSftpCredentialReferenceRead,
    ExternalDocumentSourceSftpCredentialReferenceReceiptRead,
    ExternalDocumentSourceSftpCredentialReferenceRequest,
)
from app.modules.external_document_sources.sftp_credential_reference_service import (
    approve_external_document_source_sftp_credential_reference,
    disable_external_document_source_sftp_credential_reference,
    get_external_document_source_sftp_credential_reference,
    list_external_document_source_sftp_credential_reference_receipts,
    reject_external_document_source_sftp_credential_reference,
    request_external_document_source_sftp_credential_reference,
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


def _audit_values(binding) -> dict:
    return {
        "profile_id": str(binding.profile_id),
        "provider_kind": "sftp",
        "authentication_kind": binding.authentication_kind,
        "reference_backend": binding.reference_backend,
        "locator_hash": binding.locator_hash,
        "scope_hash": binding.scope_hash,
        "status": binding.status,
        "credential_reference_stored": True,
        "credential_stored": False,
        "secret_resolution_performed": False,
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
    "/profiles/{profile_id}/sftp-credential-reference-bindings",
    response_model=ExternalDocumentSourceSftpCredentialReferenceRead,
    status_code=status.HTTP_201_CREATED,
)
def request_sftp_credential_reference_endpoint(
    profile_id: UUID,
    payload: ExternalDocumentSourceSftpCredentialReferenceRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialReferenceRead:
    try:
        binding, outcome = request_external_document_source_sftp_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
            authentication_kind=payload.authentication_kind,
            reference_backend=payload.reference_backend,
            reference_namespace=payload.reference_namespace,
            reference_name=payload.reference_name,
            reference_version=payload.reference_version,
        )
        if outcome == "requested":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_CREDENTIAL_REFERENCE_REQUESTED",
                entity_type="external_document_source_sftp_credential_reference_binding",
                entity_id=binding.id,
                new_values=_audit_values(binding),
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceSftpCredentialReferenceRead.model_validate(binding)


@router.post(
    "/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/approve",
    response_model=ExternalDocumentSourceSftpCredentialReferenceRead,
)
def approve_sftp_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceSftpCredentialReferenceDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialReferenceRead:
    try:
        binding, outcome = approve_external_document_source_sftp_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            approved_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "approved":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_CREDENTIAL_REFERENCE_APPROVED",
                entity_type="external_document_source_sftp_credential_reference_binding",
                entity_id=binding.id,
                new_values={
                    **_audit_values(binding),
                    "approval_hash": binding.approval_hash,
                },
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceSftpCredentialReferenceRead.model_validate(binding)


@router.post(
    "/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/reject",
    response_model=ExternalDocumentSourceSftpCredentialReferenceRead,
)
def reject_sftp_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceSftpCredentialReferenceDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialReferenceRead:
    try:
        binding, outcome = reject_external_document_source_sftp_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            rejected_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "rejected":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_CREDENTIAL_REFERENCE_REJECTED",
                entity_type="external_document_source_sftp_credential_reference_binding",
                entity_id=binding.id,
                new_values={
                    **_audit_values(binding),
                    "terminal_hash": binding.terminal_hash,
                },
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceSftpCredentialReferenceRead.model_validate(binding)


@router.post(
    "/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/disable",
    response_model=ExternalDocumentSourceSftpCredentialReferenceRead,
)
def disable_sftp_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceSftpCredentialReferenceDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialReferenceRead:
    try:
        binding, outcome = disable_external_document_source_sftp_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            disabled_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "disabled":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_CREDENTIAL_REFERENCE_DISABLED",
                entity_type="external_document_source_sftp_credential_reference_binding",
                entity_id=binding.id,
                new_values={
                    **_audit_values(binding),
                    "terminal_hash": binding.terminal_hash,
                },
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceSftpCredentialReferenceRead.model_validate(binding)


@router.get(
    "/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}",
    response_model=ExternalDocumentSourceSftpCredentialReferenceRead,
)
def get_sftp_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCredentialReferenceRead:
    try:
        binding = get_external_document_source_sftp_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
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
    return ExternalDocumentSourceSftpCredentialReferenceRead.model_validate(binding)


@router.get(
    "/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpCredentialReferenceReceiptRead],
)
def list_sftp_credential_reference_receipts_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpCredentialReferenceReceiptRead]:
    try:
        rows = list_external_document_source_sftp_credential_reference_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
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
        ExternalDocumentSourceSftpCredentialReferenceReceiptRead.model_validate(row)
        for row in rows
    ]
