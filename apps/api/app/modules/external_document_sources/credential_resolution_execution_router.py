from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.credential_resolution_execution_schemas import (
    ExternalDocumentSourceCredentialResolutionExecutionRead,
    ExternalDocumentSourceCredentialResolutionExecutionReceiptRead,
    ExternalDocumentSourceCredentialResolutionExecutionRequest,
)
from app.modules.external_document_sources.credential_resolution_execution_service import (
    execute_external_document_source_credential_resolution,
    get_external_document_source_credential_resolution_execution,
    list_external_document_source_credential_resolution_execution_receipts,
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
        "activation_execution_id": str(execution.activation_execution_id),
        "authorization_id": str(execution.authorization_id),
        "health_qualification_id": str(execution.health_qualification_id),
        "credential_reference_binding_id": str(execution.credential_reference_binding_id),
        "provider_kind": execution.provider_kind,
        "reference_backend": execution.reference_backend,
        "resolution_resolver_kind": execution.resolution_resolver_kind,
        "locator_hash": execution.locator_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "completion_hash": execution.completion_hash,
        "status": execution.status,
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": execution.credential_reference_resolution_performed,
        "activation_authorization_consumed": True,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "oauth_token_exchanged": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_client_activation_authorized": False,
        "provider_network_performed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "subscription_created": False,
        "checkpoint_created": False,
        "sync_executed": False,
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/provider-client-activation-executions/{activation_execution_id}/credential-resolution-executions",
    response_model=ExternalDocumentSourceCredentialResolutionExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_credential_resolution_endpoint(
    profile_id: UUID,
    activation_execution_id: UUID,
    payload: ExternalDocumentSourceCredentialResolutionExecutionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialResolutionExecutionRead:
    try:
        execution, outcome = execute_external_document_source_credential_resolution(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            activation_execution_id=activation_execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CREDENTIAL_REFERENCE_RESOLUTION_EXECUTED",
                entity_type="external_document_source_credential_resolution_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details="Phase 17.5-I resolved the exact governed credential reference only inside the bounded resolver execution; no secret value was returned or persisted and no OAuth/token, provider-network, remote-document, Evidence, Document or claim authority was exercised.",
            )
            db.commit()
            db.refresh(execution)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceCredentialResolutionExecutionRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/credential-resolution-executions/{execution_id}",
    response_model=ExternalDocumentSourceCredentialResolutionExecutionRead,
)
def get_credential_resolution_execution_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialResolutionExecutionRead:
    try:
        execution = get_external_document_source_credential_resolution_execution(
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
    return ExternalDocumentSourceCredentialResolutionExecutionRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/credential-resolution-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceCredentialResolutionExecutionReceiptRead],
)
def list_credential_resolution_execution_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceCredentialResolutionExecutionReceiptRead]:
    try:
        receipts = list_external_document_source_credential_resolution_execution_receipts(
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
    return [ExternalDocumentSourceCredentialResolutionExecutionReceiptRead.model_validate(row) for row in receipts]
