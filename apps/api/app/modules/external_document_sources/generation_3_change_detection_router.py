from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.generation_3_change_detection_schemas import (
    ExternalDocumentSourceGeneration3ChangeDetectionRead,
    ExternalDocumentSourceGeneration3ChangeDetectionReceiptRead,
    ExternalDocumentSourceGeneration3ChangeDetectionRequest,
)
from app.modules.external_document_sources.generation_3_change_detection_service import (
    execute_external_document_source_generation_3_change_detection,
    get_external_document_source_generation_3_change_detection,
    list_external_document_source_generation_3_change_detection_receipts,
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
        "checkpoint_generation_3_execution_id": str(execution.checkpoint_generation_3_execution_id),
        "successor_versioned_restaging_execution_id": str(execution.successor_versioned_restaging_execution_id),
        "successor_change_detection_execution_id": str(execution.successor_change_detection_execution_id),
        "predecessor_checkpoint_generation_execution_id": str(execution.predecessor_checkpoint_generation_execution_id),
        "versioned_restaging_execution_id": str(execution.versioned_restaging_execution_id),
        "predecessor_sync_checkpoint_execution_id": str(execution.predecessor_sync_checkpoint_execution_id),
        "change_detection_execution_id": str(execution.change_detection_execution_id),
        "listing_execution_id": str(execution.listing_execution_id),
        "metadata_item_id": str(execution.metadata_item_id),
        "provider_kind": execution.provider_kind,
        "profile_hash": execution.profile_hash,
        "baseline_generation": execution.baseline_generation,
        "successor_checkpoint_kind": execution.successor_checkpoint_kind,
        "successor_checkpoint_state_hash": execution.successor_checkpoint_state_hash,
        "successor_checkpoint_completion_hash": execution.successor_checkpoint_completion_hash,
        "candidate_content_proof_hash": execution.candidate_content_proof_hash,
        "candidate_completion_hash": execution.candidate_completion_hash,
        "successor_change_scope_hash": execution.successor_change_scope_hash,
        "successor_change_request_hash": execution.successor_change_request_hash,
        "successor_change_completion_hash": execution.successor_change_completion_hash,
        "baseline_projection_hash": execution.baseline_projection_hash,
        "baseline_provider_item_id_hash": execution.baseline_provider_item_id_hash,
        "observation_operation_kind": execution.observation_operation_kind,
        "observation_adapter_kind": execution.observation_adapter_kind,
        "endpoint_policy_hash": execution.endpoint_policy_hash,
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "result_status": execution.result_status,
        "observed_projection_hash": execution.observed_projection_hash,
        "observed_provider_item_id_hash": execution.observed_provider_item_id_hash,
        "observed_version_token_hash": execution.observed_version_token_hash,
        "observed_byte_size": execution.observed_byte_size,
        "observed_modified_at": execution.observed_modified_at.isoformat() if execution.observed_modified_at else None,
        "observed_mime_type_class": execution.observed_mime_type_class,
        "changed_dimensions": execution.changed_dimensions,
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
        "upstream_checkpoint_generation_advance_completed": True,
        "upstream_successor_change_detection_completed": True,
        "upstream_successor_versioned_restaging_completed": True,
        "upstream_checkpoint_generation_3_advance_completed": True,
        "provider_client_constructed": True,
        "exact_item_metadata_read_performed": True,
        "generation_3_successor_change_detection_completed": True,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "durable_content_staged": False,
        "checkpoint_created": False,
        "checkpoint_advanced": False,
        "sync_executed": False,
        "subscription_created": False,
        "document_created": False,
        "evidence_admitted": False,
        "content_parsed": False,
        "content_extracted": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/checkpoint-generation-3-executions/{checkpoint_generation_3_execution_id}/generation-3-successor-change-detection-executions",
    response_model=ExternalDocumentSourceGeneration3ChangeDetectionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_generation_3_change_detection_endpoint(
    profile_id: UUID,
    checkpoint_generation_3_execution_id: UUID,
    payload: ExternalDocumentSourceGeneration3ChangeDetectionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceGeneration3ChangeDetectionRead:
    try:
        execution, outcome = execute_external_document_source_generation_3_change_detection(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            checkpoint_generation_3_execution_id=checkpoint_generation_3_execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_GENERATION_3_EXACT_ITEM_CHANGE_DETECTION_COMPLETED",
                entity_type="external_document_source_generation_3_change_detection_execution",
                entity_id=execution.id,
                new_values=_execution_audit_values(execution),
                details=(
                    "Phase 17.5-V performed one explicit metadata-only observation of the exact provider item against the immutable generation-3 checkpoint. "
                    "No folder listing, file-body read, object-store access, restaging, checkpoint advancement, recurring sync/subscription, Document creation, Evidence admission, parsing/OCR or Claim mutation was performed."
                ),
            )
            db.commit()
            db.refresh(execution)
        return ExternalDocumentSourceGeneration3ChangeDetectionRead.model_validate(execution)
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
    "/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}",
    response_model=ExternalDocumentSourceGeneration3ChangeDetectionRead,
)
def get_generation_3_change_detection_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceGeneration3ChangeDetectionRead:
    try:
        execution = get_external_document_source_generation_3_change_detection(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceGeneration3ChangeDetectionRead.model_validate(execution)
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
    "/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceGeneration3ChangeDetectionReceiptRead],
)
def list_generation_3_change_detection_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceGeneration3ChangeDetectionReceiptRead]:
    try:
        receipts = list_external_document_source_generation_3_change_detection_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [ExternalDocumentSourceGeneration3ChangeDetectionReceiptRead.model_validate(row) for row in receipts]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
