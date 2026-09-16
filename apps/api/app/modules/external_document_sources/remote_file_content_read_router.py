from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.remote_file_content_read_schemas import (
    ExternalDocumentSourceRemoteFileContentReadRead,
    ExternalDocumentSourceRemoteFileContentReadReceiptRead,
    ExternalDocumentSourceRemoteFileContentReadRequest,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    execute_external_document_source_remote_file_content_read,
    get_external_document_source_remote_file_content_read,
    list_external_document_source_remote_file_content_read_receipts,
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
        "listing_execution_id": str(execution.listing_execution_id),
        "metadata_item_id": str(execution.metadata_item_id),
        "provider_client_health_execution_id": str(execution.provider_client_health_execution_id),
        "token_acquisition_execution_id": str(execution.token_acquisition_execution_id),
        "credential_resolution_execution_id": str(execution.credential_resolution_execution_id),
        "credential_reference_binding_id": str(execution.credential_reference_binding_id),
        "provider_kind": execution.provider_kind,
        "reference_backend": execution.reference_backend,
        "client_kind": execution.client_kind,
        "listing_operation_kind": execution.listing_operation_kind,
        "list_adapter_kind": execution.list_adapter_kind,
        "listing_scope_hash": execution.listing_scope_hash,
        "listing_request_hash": execution.listing_request_hash,
        "listing_completion_hash": execution.listing_completion_hash,
        "listing_items_hash": execution.listing_items_hash,
        "metadata_item_hash": execution.metadata_item_hash,
        "metadata_item_version_token_hash": execution.metadata_item_version_token_hash,
        "declared_byte_size": execution.declared_byte_size,
        "metadata_mime_type_class": execution.metadata_mime_type_class,
        "read_operation_kind": execution.read_operation_kind,
        "read_adapter_kind": execution.read_adapter_kind,
        "endpoint_policy_hash": execution.endpoint_policy_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "completion_hash": execution.completion_hash,
        "status": execution.status,
        "result_status": execution.result_status,
        "content_sha256": execution.content_sha256,
        "content_byte_count": execution.content_byte_count,
        "media_type_class": execution.media_type_class,
        "latency_class": execution.latency_class,
        "observed_version_token_hash": execution.observed_version_token_hash,
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "provider_client_constructed": execution.provider_client_constructed,
        "remote_content_transiently_observed": execution.remote_content_transiently_observed,
        "remote_read_performed": execution.remote_read_performed,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "id_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_client_stored": False,
        "provider_response_body_stored": False,
        "remote_content_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "remote_list_performed": False,
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
    "/profiles/{profile_id}/remote-metadata-listing-executions/{listing_execution_id}/items/{metadata_item_id}/remote-content-read-executions",
    response_model=ExternalDocumentSourceRemoteFileContentReadRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_remote_file_content_read_endpoint(
    profile_id: UUID,
    listing_execution_id: UUID,
    metadata_item_id: UUID,
    payload: ExternalDocumentSourceRemoteFileContentReadRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceRemoteFileContentReadRead:
    try:
        execution, outcome = execute_external_document_source_remote_file_content_read(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            listing_execution_id=listing_execution_id,
            metadata_item_id=metadata_item_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_REMOTE_FILE_CONTENT_READ_EXECUTED",
                entity_type="external_document_source_remote_file_content_read_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details=(
                    "Phase 17.5-M read exactly one previously observed Phase L remote file item under the governed provider boundary, "
                    "verified only a bounded byte count, SHA-256 digest, media/version proof and timing class, and discarded the transient file bytes before service return. "
                    "No remote content bytes, extracted text, provider response body, download URL, reusable client/session, synchronization/checkpoint, Document, Evidence or claim authority was persisted or returned."
                ),
            )
            db.commit()
            db.refresh(execution)
        return ExternalDocumentSourceRemoteFileContentReadRead.model_validate(execution)
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
    "/profiles/{profile_id}/remote-content-read-executions/{execution_id}",
    response_model=ExternalDocumentSourceRemoteFileContentReadRead,
)
def get_remote_file_content_read_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceRemoteFileContentReadRead:
    try:
        execution = get_external_document_source_remote_file_content_read(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceRemoteFileContentReadRead.model_validate(execution)
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
    "/profiles/{profile_id}/remote-content-read-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceRemoteFileContentReadReceiptRead],
)
def list_remote_file_content_read_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceRemoteFileContentReadReceiptRead]:
    try:
        receipts = list_external_document_source_remote_file_content_read_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [ExternalDocumentSourceRemoteFileContentReadReceiptRead.model_validate(row) for row in receipts]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)