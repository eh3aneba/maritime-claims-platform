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
from app.modules.external_document_sources.sftp_transport_verification_schemas import (
    ExternalDocumentSourceSftpTransportVerificationRead,
    ExternalDocumentSourceSftpTransportVerificationReceiptRead,
    ExternalDocumentSourceSftpTransportVerificationRequest,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    get_external_document_source_sftp_transport_verification,
    list_external_document_source_sftp_transport_verification_receipts,
    verify_external_document_source_sftp_transport,
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


def _audit_values(row) -> dict:
    return {
        "profile_id": str(row.profile_id),
        "handshake_execution_id": str(row.handshake_execution_id),
        "provider_kind": row.provider_kind,
        "destination_hostname": row.destination_hostname,
        "destination_port": row.destination_port,
        "adapter_kind": row.adapter_kind,
        "verification_limit": row.verification_limit,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "result_hash": row.result_hash,
        "result_status": row.result_status,
        "failure_code": row.failure_code,
        "host_key_algorithm": row.host_key_algorithm,
        "latency_class": row.latency_class,
        "credential_reference_stored": True,
        "provider_network_performed": row.provider_network_performed,
        "ssh_transport_performed": row.ssh_transport_performed,
        "host_key_verification_performed": (
            row.host_key_verification_performed
        ),
        "host_key_verified": row.host_key_verified,
        "secret_resolution_performed": False,
        "credential_stored": False,
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
    "/profiles/{profile_id}/sftp-handshake-executions/{execution_id}/transport-verifications",
    response_model=ExternalDocumentSourceSftpTransportVerificationRead,
    status_code=status.HTTP_201_CREATED,
)
def verify_sftp_transport_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    payload: ExternalDocumentSourceSftpTransportVerificationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpTransportVerificationRead:
    try:
        row, outcome = verify_external_document_source_sftp_transport(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            handshake_execution_id=execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            verified = row.result_status == "verified"
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=(
                    "EXTERNAL_DOCUMENT_SOURCE_SFTP_TRANSPORT_VERIFIED"
                    if verified
                    else "EXTERNAL_DOCUMENT_SOURCE_SFTP_TRANSPORT_VERIFICATION_FAILED"
                ),
                entity_type="external_document_source_sftp_transport_verification",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-F verified one bounded SSH transport and pinned host key "
                    "without resolving credentials, authenticating a user, opening an "
                    "SFTP subsystem, touching remote files or mutating Evidence, Documents, "
                    "processing, AI or Claims."
                    if verified
                    else
                    "Phase 17.6-F failed closed with a bounded sanitized transport-verification "
                    "result; no credential resolution, user authentication, SFTP subsystem, "
                    "remote-file operation, Evidence, Document, processing, AI or Claim "
                    "authority was exercised."
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
    return ExternalDocumentSourceSftpTransportVerificationRead.model_validate(row)


@router.get(
    "/profiles/{profile_id}/sftp-transport-verifications/{verification_id}",
    response_model=ExternalDocumentSourceSftpTransportVerificationRead,
)
def get_sftp_transport_verification_endpoint(
    profile_id: UUID,
    verification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpTransportVerificationRead:
    try:
        row = get_external_document_source_sftp_transport_verification(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            verification_id=verification_id,
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
    return ExternalDocumentSourceSftpTransportVerificationRead.model_validate(row)


@router.get(
    "/profiles/{profile_id}/sftp-transport-verifications/{verification_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpTransportVerificationReceiptRead],
)
def list_sftp_transport_verification_receipts_endpoint(
    profile_id: UUID,
    verification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpTransportVerificationReceiptRead]:
    try:
        rows = list_external_document_source_sftp_transport_verification_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            verification_id=verification_id,
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
        ExternalDocumentSourceSftpTransportVerificationReceiptRead.model_validate(
            row
        )
        for row in rows
    ]
