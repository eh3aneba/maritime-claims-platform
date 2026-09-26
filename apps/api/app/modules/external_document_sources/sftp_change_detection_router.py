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
from app.modules.external_document_sources.sftp_change_detection_schemas import (
    ExternalDocumentSourceSftpChangeDetectionRead,
    ExternalDocumentSourceSftpChangeDetectionReceiptRead,
    ExternalDocumentSourceSftpChangeDetectionRequest,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    execute_external_document_source_sftp_change_detection,
    get_external_document_source_sftp_change_detection,
    list_external_document_source_sftp_change_detection_receipts,
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
        "checkpoint_id": str(row.checkpoint_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "credential_reference_binding_id": str(row.credential_reference_binding_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "checkpoint_state_hash": row.checkpoint_state_hash,
        "checkpoint_completion_hash": row.checkpoint_completion_hash,
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
        "credential_reference_stored": True,
        "upstream_checkpoint_completed": True,
        "secret_resolution_performed": True,
        "credential_stored": False,
        "session_stored": False,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": True,
        "authentication_performed": True,
        "authentication_succeeded": True,
        "sftp_session_opened": True,
        "sftp_session_closed": True,
        "exact_item_metadata_read_performed": True,
        "change_detection_completed": True,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_stat_performed": True,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_rename_performed": False,
        "remote_delete_performed": False,
        "remote_mkdir_performed": False,
        "remote_chmod_performed": False,
        "remote_chown_performed": False,
        "remote_touch_performed": False,
        "command_executed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "storage_copy_performed": False,
        "checkpoint_advanced": False,
        "subscription_created": False,
        "raw_response_stored": False,
        "remote_content_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/sftp-checkpoints/{checkpoint_id}/change-detections",
    response_model=ExternalDocumentSourceSftpChangeDetectionRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_change_detection_endpoint(
    profile_id: UUID,
    checkpoint_id: UUID,
    payload: ExternalDocumentSourceSftpChangeDetectionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpChangeDetectionRead:
    try:
        row, outcome = execute_external_document_source_sftp_change_detection(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            checkpoint_id=checkpoint_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_EXACT_FILE_CHANGE_DETECTED",
                entity_type="external_document_source_sftp_change_detection",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-L performed one exact-path metadata/stat observation "
                    "against the immutable Phase 17.6-K checkpoint and classified "
                    "the exact file as unchanged, changed or canonical missing. "
                    "No directory listing, file-content read, storage I/O, checkpoint "
                    "advancement, Document/Evidence creation, processing, AI or Claim "
                    "mutation was authorized or performed."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpChangeDetectionRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-change-detections/{execution_id}",
    response_model=ExternalDocumentSourceSftpChangeDetectionRead,
)
def get_sftp_change_detection_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpChangeDetectionRead:
    try:
        row = get_external_document_source_sftp_change_detection(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return ExternalDocumentSourceSftpChangeDetectionRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-change-detections/{execution_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpChangeDetectionReceiptRead],
)
def list_sftp_change_detection_receipts_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpChangeDetectionReceiptRead]:
    try:
        rows = list_external_document_source_sftp_change_detection_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        return [
            ExternalDocumentSourceSftpChangeDetectionReceiptRead.model_validate(row)
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
