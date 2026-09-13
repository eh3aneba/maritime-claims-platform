from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import (
    ConnectionAuthorizationAdminMfa,
    _commit_expiry_if_needed,
)
from app.modules.external_document_sources.connection_bootstrap_schemas import (
    ExternalDocumentSourceConnectionBootstrapExecutionRead,
    ExternalDocumentSourceConnectionBootstrapExecutionReceiptRead,
    ExternalDocumentSourceConnectionBootstrapExecutionRequest,
)
from app.modules.external_document_sources.connection_bootstrap_service import (
    execute_external_document_source_connection_bootstrap,
    get_external_document_source_connection_bootstrap_execution,
    list_external_document_source_connection_bootstrap_execution_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User

router = APIRouter()


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/profiles/{profile_id}/connection-authorizations/{authorization_id}/bootstrap-executions",
    response_model=ExternalDocumentSourceConnectionBootstrapExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_connection_bootstrap_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceConnectionBootstrapExecutionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceConnectionBootstrapExecutionRead:
    try:
        execution, authorization, outcome = execute_external_document_source_connection_bootstrap(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "expired":
            _commit_expiry_if_needed(
                db,
                current_user=current_user,
                authorization=authorization,
                outcome="expired",
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="External provider connection authorization is no longer consumable",
            )
        if execution is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="External provider bootstrap execution failed")
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CONNECTION_BOOTSTRAP_CONSUMED",
                entity_type="external_document_source_connection_bootstrap_execution",
                entity_id=execution.id,
                new_values={
                    "profile_id": str(execution.profile_id),
                    "discovery_run_id": str(execution.discovery_run_id),
                    "authorization_id": str(execution.authorization_id),
                    "scope_hash": execution.scope_hash,
                    "request_hash": execution.request_hash,
                    "completion_hash": execution.completion_hash,
                    "authorization_terminal_hash": execution.authorization_terminal_hash,
                    "status": execution.status,
                    "authorization_consumed": True,
                    "credential_stored": False,
                    "credential_reference_stored": False,
                    "oauth_token_exchanged": False,
                    "provider_network_performed": False,
                    "remote_read_performed": False,
                    "evidence_admitted": False,
                    "document_created": False,
                    "claim_mutated": False,
                },
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
    return ExternalDocumentSourceConnectionBootstrapExecutionRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/bootstrap-executions/{execution_id}",
    response_model=ExternalDocumentSourceConnectionBootstrapExecutionRead,
)
def get_connection_bootstrap_execution_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceConnectionBootstrapExecutionRead:
    try:
        execution = get_external_document_source_connection_bootstrap_execution(
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
    return ExternalDocumentSourceConnectionBootstrapExecutionRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/bootstrap-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceConnectionBootstrapExecutionReceiptRead],
)
def list_connection_bootstrap_execution_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceConnectionBootstrapExecutionReceiptRead]:
    try:
        receipts = list_external_document_source_connection_bootstrap_execution_receipts(
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
    return [ExternalDocumentSourceConnectionBootstrapExecutionReceiptRead.model_validate(receipt) for receipt in receipts]
