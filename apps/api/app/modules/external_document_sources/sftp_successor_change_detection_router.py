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
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_successor_change_detection_schemas import (
    ExternalDocumentSourceSftpSuccessorChangeDetectionRead,
    ExternalDocumentSourceSftpSuccessorChangeDetectionReceiptRead,
    ExternalDocumentSourceSftpSuccessorChangeDetectionRequest,
)
from app.modules.external_document_sources.sftp_successor_change_detection_service import (
    execute_external_document_source_sftp_successor_change_detection,
    get_external_document_source_sftp_successor_change_detection,
    list_external_document_source_sftp_successor_change_detection_receipts,
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
        "checkpoint_advancement_id": str(row.checkpoint_advancement_id),
        "successor_restaging_id": str(row.successor_restaging_id),
        "predecessor_checkpoint_id": str(row.predecessor_checkpoint_id),
        "change_detection_id": str(row.change_detection_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "credential_reference_binding_id": str(row.credential_reference_binding_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "baseline_generation": row.baseline_generation,
        "successor_checkpoint_kind": row.successor_checkpoint_kind,
        "successor_checkpoint_state_hash": row.successor_checkpoint_state_hash,
        "successor_checkpoint_completion_hash": row.successor_checkpoint_completion_hash,
        "candidate_content_proof_hash": row.candidate_content_proof_hash,
        "candidate_completion_hash": row.candidate_completion_hash,
        "baseline_projection_hash": row.baseline_projection_hash,
        "baseline_entry_hash": row.baseline_entry_hash,
        "baseline_relative_path_hash": row.baseline_relative_path_hash,
        "baseline_entry_kind": row.baseline_entry_kind,
        "baseline_byte_size": row.baseline_byte_size,
        "baseline_modified_at": row.baseline_modified_at.isoformat() if row.baseline_modified_at else None,
        "baseline_metadata_id_hash": row.baseline_metadata_id_hash,
        "observation_operation_kind": row.observation_operation_kind,
        "observation_adapter_kind": row.observation_adapter_kind,
        "observation_policy_hash": row.observation_policy_hash,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "observed_projection_hash": row.observed_projection_hash,
        "observed_entry_kind": row.observed_entry_kind,
        "observed_byte_size": row.observed_byte_size,
        "observed_modified_at": row.observed_modified_at.isoformat() if row.observed_modified_at else None,
        "observed_metadata_id_hash": row.observed_metadata_id_hash,
        "changed_dimensions": row.changed_dimensions,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completion_hash": row.completion_hash,
        "result_status": row.result_status,
        **{
            field: bool(getattr(row, field))
            for field in (
                "credential_reference_stored", "upstream_predecessor_checkpoint_completed",
                "upstream_change_detection_completed", "upstream_successor_restaging_completed",
                "upstream_checkpoint_advancement_completed", "secret_resolution_performed",
                "credential_stored", "session_stored", "provider_network_performed",
                "ssh_transport_performed", "host_key_verification_performed", "host_key_verified",
                "authentication_performed", "authentication_succeeded", "sftp_session_opened",
                "sftp_session_closed", "exact_item_metadata_read_performed",
                "successor_change_detection_completed", "remote_content_transiently_observed",
                "remote_list_performed", "remote_stat_performed", "remote_read_performed",
                "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
                "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
                "remote_touch_performed", "command_executed", "storage_read_performed",
                "storage_write_performed", "storage_reconciliation_performed",
                "storage_delete_performed", "storage_copy_performed", "durable_content_staged",
                "checkpoint_created", "checkpoint_advanced", "subscription_created",
                "raw_response_stored", "remote_content_stored", "remote_content_returned",
                "remote_content_logged", "content_parsed", "content_extracted",
                "evidence_admitted", "document_created", "processing_enqueued",
                "ai_executed", "claim_mutated",
            )
        },
    }


@router.post(
    "/profiles/{profile_id}/sftp-checkpoint-advancements/{advancement_id}/successor-change-detections",
    response_model=ExternalDocumentSourceSftpSuccessorChangeDetectionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_successor_change_detection_endpoint(
    profile_id: UUID,
    advancement_id: UUID,
    payload: ExternalDocumentSourceSftpSuccessorChangeDetectionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpSuccessorChangeDetectionRead:
    try:
        row, outcome = execute_external_document_source_sftp_successor_change_detection(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            checkpoint_advancement_id=advancement_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_SUCCESSOR_CHANGE_DETECTED",
                entity_type="external_document_source_sftp_successor_change_detection",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-O performed one exact-path metadata/stat observation against "
                    "the integrity-valid Phase 17.6-N generation-2 checkpoint and classified "
                    "the exact file as unchanged, changed or canonical missing. The generation-2 "
                    "baseline came from the L observed metadata consumed by M/N, not the stale K "
                    "generation-1 state. No directory listing, file-content read, object-storage "
                    "I/O, checkpoint advancement, Document/Evidence creation, processing, AI, "
                    "Claim mutation or recurring scheduling was authorized or performed."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpSuccessorChangeDetectionRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-successor-change-detections/{execution_id}",
    response_model=ExternalDocumentSourceSftpSuccessorChangeDetectionRead,
)
def get_sftp_successor_change_detection_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpSuccessorChangeDetectionRead:
    try:
        row = get_external_document_source_sftp_successor_change_detection(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceSftpSuccessorChangeDetectionRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-successor-change-detections/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpSuccessorChangeDetectionReceiptRead],
)
def list_sftp_successor_change_detection_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpSuccessorChangeDetectionReceiptRead]:
    try:
        rows = list_external_document_source_sftp_successor_change_detection_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceSftpSuccessorChangeDetectionReceiptRead.model_validate(row)
            for row in rows
        ]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
