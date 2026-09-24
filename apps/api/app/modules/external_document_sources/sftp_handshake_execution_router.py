from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.sftp_handshake_authorization_models import (
    ExternalDocumentSourceSftpHandshakeAuthorization,
)
from app.modules.external_document_sources.sftp_handshake_execution_schemas import (
    ExternalDocumentSourceSftpHandshakeExecutionRead,
    ExternalDocumentSourceSftpHandshakeExecutionReceiptRead,
    ExternalDocumentSourceSftpHandshakeExecutionRequest,
)
from app.modules.external_document_sources.sftp_handshake_execution_service import (
    execute_external_document_source_sftp_handshake_authorization,
    get_external_document_source_sftp_handshake_execution,
    list_external_document_source_sftp_handshake_execution_receipts,
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


def _execution_audit_values(execution) -> dict:
    return {
        "profile_id": str(execution.profile_id),
        "authorization_id": str(execution.authorization_id),
        "health_qualification_id": str(execution.health_qualification_id),
        "credential_reference_binding_id": str(
            execution.credential_reference_binding_id
        ),
        "provider_kind": execution.provider_kind,
        "authentication_kind": execution.authentication_kind,
        "reference_backend": execution.reference_backend,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "completion_hash": execution.completion_hash,
        "authorization_terminal_hash": execution.authorization_terminal_hash,
        "status": execution.status,
        "execution_limit": execution.execution_limit,
        "credential_reference_stored": True,
        "handshake_authorization_consumed": (
            execution.handshake_authorization_consumed
        ),
        "secret_resolution_performed": False,
        "credential_stored": False,
        "sftp_handshake_authorized": False,
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
    "/profiles/{profile_id}/sftp-handshake-authorizations/{authorization_id}/activation-executions",
    response_model=ExternalDocumentSourceSftpHandshakeExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_handshake_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceSftpHandshakeExecutionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpHandshakeExecutionRead:
    try:
        execution, outcome = execute_external_document_source_sftp_handshake_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "expired":
            authorization = db.scalar(
                select(ExternalDocumentSourceSftpHandshakeAuthorization).where(
                    ExternalDocumentSourceSftpHandshakeAuthorization.id == authorization_id,
                    ExternalDocumentSourceSftpHandshakeAuthorization.organization_id == current_user.organization_id,
                    ExternalDocumentSourceSftpHandshakeAuthorization.profile_id == profile_id,
                )
            )
            if authorization is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SFTP handshake authorization expired")
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_HANDSHAKE_AUTHORIZATION_EXPIRED",
                entity_type="external_document_source_sftp_handshake_authorization",
                entity_id=authorization.id,
                new_values={
                    "profile_id": str(authorization.profile_id),
                    "status": authorization.status,
                    "terminal_hash": authorization.terminal_hash,
                    "sftp_handshake_authorized": False,
                    "oauth_token_exchanged": False,
                    "provider_network_performed": False,
                    "remote_read_performed": False,
                    "evidence_admitted": False,
                },
                details="Bounded SFTP handshake authorization expired before Phase 17.6-E consumption.",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="SFTP handshake authorization is no longer consumable",
            )
        if execution is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SFTP handshake execution failed")
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_HANDSHAKE_AUTHORIZATION_CONSUMED",
                entity_type="external_document_source_sftp_handshake_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details="Phase 17.6-E consumed one bounded activation authorization locally; no credential resolution, OAuth/token exchange, provider network, remote document, Evidence, Document or claim authority was exercised.",
            )
            db.commit()
            db.refresh(execution)
    except HTTPException:
        raise
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceSftpHandshakeExecutionRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/sftp-handshake-executions/{execution_id}",
    response_model=ExternalDocumentSourceSftpHandshakeExecutionRead,
)
def get_sftp_handshake_execution_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpHandshakeExecutionRead:
    try:
        execution = get_external_document_source_sftp_handshake_execution(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
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
    return ExternalDocumentSourceSftpHandshakeExecutionRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/sftp-handshake-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpHandshakeExecutionReceiptRead],
)
def list_sftp_handshake_execution_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpHandshakeExecutionReceiptRead]:
    try:
        receipts = list_external_document_source_sftp_handshake_execution_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
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
    return [ExternalDocumentSourceSftpHandshakeExecutionReceiptRead.model_validate(row) for row in receipts]
