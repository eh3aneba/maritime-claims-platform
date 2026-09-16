from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.remote_content_staging_schemas import (
    ExternalDocumentSourceRemoteContentStagingRead,
    ExternalDocumentSourceRemoteContentStagingReceiptRead,
    ExternalDocumentSourceRemoteContentStagingRequest,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    execute_external_document_source_remote_content_staging,
    get_external_document_source_remote_content_staging,
    list_external_document_source_remote_content_staging_receipts,
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
        "remote_content_read_execution_id": str(execution.remote_content_read_execution_id),
        "listing_execution_id": str(execution.listing_execution_id),
        "metadata_item_id": str(execution.metadata_item_id),
        "provider_kind": execution.provider_kind,
        "metadata_item_hash": execution.metadata_item_hash,
        "upstream_scope_hash": execution.upstream_scope_hash,
        "upstream_request_hash": execution.upstream_request_hash,
        "upstream_completion_hash": execution.upstream_completion_hash,
        "read_operation_kind": execution.read_operation_kind,
        "read_adapter_kind": execution.read_adapter_kind,
        "endpoint_policy_hash": execution.endpoint_policy_hash,
        "expected_content_sha256": execution.expected_content_sha256,
        "expected_content_byte_count": execution.expected_content_byte_count,
        "expected_media_type_class": execution.expected_media_type_class,
        "expected_version_token_hash": execution.expected_version_token_hash,
        "storage_backend_kind": execution.storage_backend_kind,
        "storage_purpose": execution.storage_purpose,
        "storage_object_key_hash": execution.storage_object_key_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "completion_hash": execution.completion_hash,
        "status": execution.status,
        "result_status": execution.result_status,
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "upstream_remote_file_content_read_completed": True,
        "provider_client_constructed": execution.provider_client_constructed,
        "remote_content_transiently_observed": execution.remote_content_transiently_observed,
        "remote_read_performed": execution.remote_read_performed,
        "durable_content_staged": execution.durable_content_staged,
        "remote_content_stored": execution.remote_content_stored,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "id_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_client_stored": False,
        "provider_response_body_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "remote_list_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_delete_performed": False,
        "subscription_created": False,
        "checkpoint_created": False,
        "sync_executed": False,
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/remote-content-read-executions/{remote_content_read_execution_id}/remote-content-staging-executions",
    response_model=ExternalDocumentSourceRemoteContentStagingRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_remote_content_staging_endpoint(
    profile_id: UUID,
    remote_content_read_execution_id: UUID,
    payload: ExternalDocumentSourceRemoteContentStagingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceRemoteContentStagingRead:
    try:
        execution, outcome = execute_external_document_source_remote_content_staging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            remote_content_read_execution_id=remote_content_read_execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_REMOTE_CONTENT_STAGED",
                entity_type="external_document_source_remote_content_staging_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details=(
                    "Phase 17.5-N re-read one exact Phase M-bound remote file and staged only the byte-for-byte matching body into the governed non-destructive quarantine object store. "
                    "The durable object remains non-Document and non-Evidence. No raw storage key/URL/credential, provider body/URL/token/client, synchronization/checkpoint, parsing/OCR, provider write/delete, storage delete or claim authority was exposed or exercised."
                ),
            )
            db.commit()
            db.refresh(execution)
        return ExternalDocumentSourceRemoteContentStagingRead.model_validate(execution)
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
    "/profiles/{profile_id}/remote-content-staging-executions/{execution_id}",
    response_model=ExternalDocumentSourceRemoteContentStagingRead,
)
def get_remote_content_staging_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceRemoteContentStagingRead:
    try:
        execution = get_external_document_source_remote_content_staging(
            db, organization_id=current_user.organization_id, profile_id=profile_id, execution_id=execution_id,
        )
        return ExternalDocumentSourceRemoteContentStagingRead.model_validate(execution)
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
    "/profiles/{profile_id}/remote-content-staging-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceRemoteContentStagingReceiptRead],
)
def list_remote_content_staging_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceRemoteContentStagingReceiptRead]:
    try:
        receipts = list_external_document_source_remote_content_staging_receipts(
            db, organization_id=current_user.organization_id, profile_id=profile_id, execution_id=execution_id,
        )
        return [ExternalDocumentSourceRemoteContentStagingReceiptRead.model_validate(row) for row in receipts]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
