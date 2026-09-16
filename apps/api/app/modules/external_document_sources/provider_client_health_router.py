from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.provider_client_health_schemas import (
    ExternalDocumentSourceProviderClientHealthRead,
    ExternalDocumentSourceProviderClientHealthReceiptRead,
    ExternalDocumentSourceProviderClientHealthRequest,
)
from app.modules.external_document_sources.provider_client_health_service import (
    execute_external_document_source_provider_client_health,
    get_external_document_source_provider_client_health,
    list_external_document_source_provider_client_health_receipts,
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
        "token_acquisition_execution_id": str(execution.token_acquisition_execution_id),
        "credential_resolution_execution_id": str(execution.credential_resolution_execution_id),
        "credential_reference_binding_id": str(execution.credential_reference_binding_id),
        "provider_kind": execution.provider_kind,
        "reference_backend": execution.reference_backend,
        "resolution_resolver_kind": execution.resolution_resolver_kind,
        "token_flow_kind": execution.token_flow_kind,
        "token_acquirer_kind": execution.token_acquirer_kind,
        "client_kind": execution.client_kind,
        "health_operation_kind": execution.health_operation_kind,
        "health_adapter_kind": execution.health_adapter_kind,
        "locator_hash": execution.locator_hash,
        "endpoint_policy_hash": execution.endpoint_policy_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "completion_hash": execution.completion_hash,
        "status": execution.status,
        "result_status": execution.result_status,
        "latency_class": execution.latency_class,
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "provider_client_constructed": execution.provider_client_constructed,
        "provider_network_health_performed": execution.provider_network_health_performed,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "id_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_client_stored": False,
        "provider_response_body_stored": False,
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
    "/profiles/{profile_id}/token-acquisition-executions/{token_acquisition_execution_id}/provider-client-health-executions",
    response_model=ExternalDocumentSourceProviderClientHealthRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_provider_client_health_endpoint(
    profile_id: UUID,
    token_acquisition_execution_id: UUID,
    payload: ExternalDocumentSourceProviderClientHealthRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceProviderClientHealthRead:
    try:
        execution, outcome = execute_external_document_source_provider_client_health(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            token_acquisition_execution_id=token_acquisition_execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_PROVIDER_CLIENT_HEALTH_EXECUTED",
                entity_type="external_document_source_provider_client_health_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details=(
                    "Phase 17.5-K constructed one transient in-memory provider client and performed one bounded non-document network/authorization health qualification for the exact governed Phase J lineage. "
                    "Credential material, tokens, provider response bodies, client and session objects remained inside the adapter call and were neither returned nor persisted. "
                    "No remote document listing/read, synchronization, Evidence, Document or claim authority was exercised."
                ),
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
    return ExternalDocumentSourceProviderClientHealthRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/provider-client-health-executions/{execution_id}",
    response_model=ExternalDocumentSourceProviderClientHealthRead,
)
def get_provider_client_health_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceProviderClientHealthRead:
    try:
        execution = get_external_document_source_provider_client_health(
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
    return ExternalDocumentSourceProviderClientHealthRead.model_validate(execution)


@router.get(
    "/profiles/{profile_id}/provider-client-health-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceProviderClientHealthReceiptRead],
)
def list_provider_client_health_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceProviderClientHealthReceiptRead]:
    try:
        receipts = list_external_document_source_provider_client_health_receipts(
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
    return [ExternalDocumentSourceProviderClientHealthReceiptRead.model_validate(row) for row in receipts]
