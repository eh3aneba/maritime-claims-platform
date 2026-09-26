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
from app.modules.external_document_sources.sftp_session_activation_schemas import (
    ExternalDocumentSourceSftpSessionActivationRead,
    ExternalDocumentSourceSftpSessionActivationReceiptRead,
    ExternalDocumentSourceSftpSessionActivationRequest,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    activate_external_document_source_sftp_session,
    get_external_document_source_sftp_session_activation,
    list_external_document_source_sftp_session_activation_receipts,
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


def _audit_values(row) -> dict:
    return {
        "profile_id": str(row.profile_id),
        "transport_verification_id": str(row.transport_verification_id),
        "health_qualification_id": str(row.health_qualification_id),
        "credential_reference_binding_id": str(row.credential_reference_binding_id),
        "provider_kind": row.provider_kind,
        "destination_hostname": row.destination_hostname,
        "destination_port": row.destination_port,
        "adapter_kind": row.adapter_kind,
        "authentication_kind": row.authentication_kind,
        "result_status": row.result_status,
        "failure_code": row.failure_code,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "result_hash": row.result_hash,
        "credential_reference_stored": True,
        "secret_resolution_performed": row.secret_resolution_performed,
        "credential_stored": False,
        "provider_network_performed": row.provider_network_performed,
        "ssh_transport_performed": row.ssh_transport_performed,
        "host_key_verification_performed": row.host_key_verification_performed,
        "host_key_verified": row.host_key_verified,
        "authentication_performed": row.authentication_performed,
        "authentication_succeeded": row.authentication_succeeded,
        "sftp_session_opened": row.sftp_session_opened,
        "sftp_session_closed": row.sftp_session_closed,
        "remote_list_performed": False,
        "remote_stat_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_rename_performed": False,
        "remote_delete_performed": False,
        "command_executed": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/sftp-transport-verifications/{verification_id}/session-activations",
    response_model=ExternalDocumentSourceSftpSessionActivationRead,
    status_code=status.HTTP_201_CREATED,
)
def activate_sftp_session_endpoint(
    profile_id: UUID,
    verification_id: UUID,
    payload: ExternalDocumentSourceSftpSessionActivationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpSessionActivationRead:
    try:
        row, outcome = activate_external_document_source_sftp_session(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            transport_verification_id=verification_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                actor_id=current_user.id,
                action="external_document_source.sftp_session_activation.completed",
                resource_type="external_document_source_sftp_session_activation",
                resource_id=row.id,
                new_values=_audit_values(row),
            )
        db.commit()
        db.refresh(row)
        return row
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        db.rollback()
        _raise_service_error(exc)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SFTP session activation conflict") from exc


@router.get(
    "/profiles/{profile_id}/sftp-session-activations/{activation_id}",
    response_model=ExternalDocumentSourceSftpSessionActivationRead,
)
def get_sftp_session_activation_endpoint(
    profile_id: UUID,
    activation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpSessionActivationRead:
    try:
        return get_external_document_source_sftp_session_activation(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            activation_id=activation_id,
        )
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/sftp-session-activations/{activation_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpSessionActivationReceiptRead],
)
def list_sftp_session_activation_receipts_endpoint(
    profile_id: UUID,
    activation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpSessionActivationReceiptRead]:
    try:
        return list_external_document_source_sftp_session_activation_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            activation_id=activation_id,
        )
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)
