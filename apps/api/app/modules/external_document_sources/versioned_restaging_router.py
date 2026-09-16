from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.versioned_restaging_schemas import (
    ExternalDocumentSourceVersionedRestagingRead,
    ExternalDocumentSourceVersionedRestagingReceiptRead,
    ExternalDocumentSourceVersionedRestagingRequest,
)
from app.modules.external_document_sources.versioned_restaging_service import (
    execute_external_document_source_versioned_restaging,
    get_external_document_source_versioned_restaging,
    list_external_document_source_versioned_restaging_receipts,
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
        "change_detection_execution_id": str(execution.change_detection_execution_id),
        "sync_checkpoint_execution_id": str(execution.sync_checkpoint_execution_id),
        "original_staging_execution_id": str(execution.original_staging_execution_id),
        "listing_execution_id": str(execution.listing_execution_id),
        "metadata_item_id": str(execution.metadata_item_id),
        "provider_kind": execution.provider_kind,
        "profile_hash": execution.profile_hash,
        "change_scope_hash": execution.change_scope_hash,
        "change_request_hash": execution.change_request_hash,
        "change_completion_hash": execution.change_completion_hash,
        "observed_projection_hash": execution.observed_projection_hash,
        "observed_provider_item_id_hash": execution.observed_provider_item_id_hash,
        "observed_version_token_hash": execution.observed_version_token_hash,
        "observed_byte_size": execution.observed_byte_size,
        "observed_mime_type_class": execution.observed_mime_type_class,
        "read_operation_kind": execution.read_operation_kind,
        "read_adapter_kind": execution.read_adapter_kind,
        "endpoint_policy_hash": execution.endpoint_policy_hash,
        "candidate_generation": execution.candidate_generation,
        "storage_backend_kind": execution.storage_backend_kind,
        "storage_purpose": execution.storage_purpose,
        "storage_object_key_hash": execution.storage_object_key_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "result_status": execution.result_status,
        "content_sha256": execution.content_sha256,
        "content_byte_count": execution.content_byte_count,
        "content_media_type_class": execution.content_media_type_class,
        "content_version_token_hash": execution.content_version_token_hash,
        "content_latency_class": execution.content_latency_class,
        "content_proof_hash": execution.content_proof_hash,
        "completion_hash": execution.completion_hash,
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "upstream_remote_file_content_read_completed": True,
        "upstream_remote_content_staging_completed": True,
        "upstream_sync_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "provider_client_constructed": True,
        "remote_content_transiently_observed": True,
        "remote_read_performed": True,
        "storage_read_performed": True,
        "storage_write_performed": True,
        "durable_content_staged": True,
        "remote_content_stored": True,
        "versioned_restaging_completed": True,
        "remote_list_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_delete_performed": False,
        "checkpoint_created": False,
        "checkpoint_advanced": False,
        "sync_executed": False,
        "subscription_created": False,
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
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/change-detection-executions/{change_detection_execution_id}/versioned-restaging-executions",
    response_model=ExternalDocumentSourceVersionedRestagingRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_versioned_restaging_endpoint(
    profile_id: UUID,
    change_detection_execution_id: UUID,
    payload: ExternalDocumentSourceVersionedRestagingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceVersionedRestagingRead:
    try:
        execution, outcome = execute_external_document_source_versioned_restaging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            change_detection_execution_id=change_detection_execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CHANGED_ITEM_VERSIONED_RESTAGING_COMPLETED",
                entity_type="external_document_source_versioned_restaging_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details=(
                    "Phase 17.5-Q reread the exact Phase P changed provider item and staged one new immutable candidate quarantine generation. "
                    "The Phase O checkpoint and original Phase N object were not advanced, replaced, overwritten or deleted; no Document, Evidence, processing/OCR, recurring sync or Claim mutation occurred."
                ),
            )
            db.commit()
            db.refresh(execution)
        return ExternalDocumentSourceVersionedRestagingRead.model_validate(execution)
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
    "/profiles/{profile_id}/versioned-restaging-executions/{execution_id}",
    response_model=ExternalDocumentSourceVersionedRestagingRead,
)
def get_versioned_restaging_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceVersionedRestagingRead:
    try:
        execution = get_external_document_source_versioned_restaging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceVersionedRestagingRead.model_validate(execution)
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
    "/profiles/{profile_id}/versioned-restaging-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceVersionedRestagingReceiptRead],
)
def list_versioned_restaging_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceVersionedRestagingReceiptRead]:
    try:
        receipts = list_external_document_source_versioned_restaging_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [ExternalDocumentSourceVersionedRestagingReceiptRead.model_validate(row) for row in receipts]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
