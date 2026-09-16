from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.checkpoint_generation_schemas import (
    ExternalDocumentSourceCheckpointGenerationRead,
    ExternalDocumentSourceCheckpointGenerationReceiptRead,
    ExternalDocumentSourceCheckpointGenerationRequest,
)
from app.modules.external_document_sources.checkpoint_generation_service import (
    execute_external_document_source_checkpoint_generation,
    get_external_document_source_checkpoint_generation,
    list_external_document_source_checkpoint_generation_receipts,
)
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
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
        "versioned_restaging_execution_id": str(execution.versioned_restaging_execution_id),
        "predecessor_sync_checkpoint_execution_id": str(execution.predecessor_sync_checkpoint_execution_id),
        "change_detection_execution_id": str(execution.change_detection_execution_id),
        "original_staging_execution_id": str(execution.original_staging_execution_id),
        "listing_execution_id": str(execution.listing_execution_id),
        "metadata_item_id": str(execution.metadata_item_id),
        "provider_kind": execution.provider_kind,
        "profile_hash": execution.profile_hash,
        "predecessor_checkpoint_generation": execution.predecessor_checkpoint_generation,
        "predecessor_checkpoint_state_hash": execution.predecessor_checkpoint_state_hash,
        "predecessor_checkpoint_completion_hash": execution.predecessor_checkpoint_completion_hash,
        "candidate_scope_hash": execution.candidate_scope_hash,
        "candidate_request_hash": execution.candidate_request_hash,
        "candidate_content_proof_hash": execution.candidate_content_proof_hash,
        "candidate_completion_hash": execution.candidate_completion_hash,
        "candidate_generation": execution.candidate_generation,
        "content_sha256": execution.content_sha256,
        "content_byte_count": execution.content_byte_count,
        "media_type_class": execution.media_type_class,
        "version_token_hash": execution.version_token_hash,
        "storage_backend_kind": execution.storage_backend_kind,
        "storage_purpose": execution.storage_purpose,
        "storage_object_key_hash": execution.storage_object_key_hash,
        "successor_checkpoint_kind": execution.successor_checkpoint_kind,
        "successor_checkpoint_generation": execution.successor_checkpoint_generation,
        "successor_checkpoint_state_hash": execution.successor_checkpoint_state_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "result_status": execution.result_status,
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
        "upstream_versioned_restaging_completed": True,
        "provider_client_constructed": False,
        "exact_item_metadata_read_performed": False,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "durable_content_staged": False,
        "checkpoint_created": True,
        "checkpoint_advanced": True,
        "checkpoint_generation_advance_completed": True,
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
    "/profiles/{profile_id}/versioned-restaging-executions/{versioned_restaging_execution_id}/checkpoint-generation-executions",
    response_model=ExternalDocumentSourceCheckpointGenerationRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_checkpoint_generation_endpoint(
    profile_id: UUID,
    versioned_restaging_execution_id: UUID,
    payload: ExternalDocumentSourceCheckpointGenerationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCheckpointGenerationRead:
    try:
        execution, outcome = execute_external_document_source_checkpoint_generation(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            versioned_restaging_execution_id=versioned_restaging_execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CHECKPOINT_GENERATION_ADVANCED",
                entity_type="external_document_source_checkpoint_generation_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details=(
                    "Phase 17.5-R recorded one immutable generation-2 successor checkpoint from the exact integrity-valid Phase O predecessor and Phase Q candidate. "
                    "No provider or object-storage I/O occurred; the predecessor checkpoint and candidate object were not mutated, and no Document, Evidence, processing/OCR, recurring sync or Claim mutation occurred."
                ),
            )
            db.commit()
            db.refresh(execution)
        return ExternalDocumentSourceCheckpointGenerationRead.model_validate(execution)
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
    "/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}",
    response_model=ExternalDocumentSourceCheckpointGenerationRead,
)
def get_checkpoint_generation_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCheckpointGenerationRead:
    try:
        execution = get_external_document_source_checkpoint_generation(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceCheckpointGenerationRead.model_validate(execution)
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
    "/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceCheckpointGenerationReceiptRead],
)
def list_checkpoint_generation_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceCheckpointGenerationReceiptRead]:
    try:
        receipts = list_external_document_source_checkpoint_generation_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [ExternalDocumentSourceCheckpointGenerationReceiptRead.model_validate(row) for row in receipts]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
