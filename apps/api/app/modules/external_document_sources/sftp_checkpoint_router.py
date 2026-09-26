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
from app.modules.external_document_sources.sftp_checkpoint_schemas import (
    ExternalDocumentSourceSftpCheckpointRead,
    ExternalDocumentSourceSftpCheckpointReceiptRead,
    ExternalDocumentSourceSftpCheckpointRequest,
)
from app.modules.external_document_sources.sftp_checkpoint_service import (
    create_external_document_source_sftp_checkpoint,
    get_external_document_source_sftp_checkpoint,
    list_external_document_source_sftp_checkpoint_receipts,
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
        "quarantine_staging_id": str(row.quarantine_staging_id),
        "file_content_proof_id": str(row.file_content_proof_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "listing_entry_hash": row.listing_entry_hash,
        "file_content_proof_result_hash": row.file_content_proof_result_hash,
        "staging_scope_hash": row.staging_scope_hash,
        "staging_request_hash": row.staging_request_hash,
        "staging_completion_hash": row.staging_completion_hash,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "checkpoint_kind": row.checkpoint_kind,
        "checkpoint_generation": row.checkpoint_generation,
        "checkpoint_state_hash": row.checkpoint_state_hash,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completion_hash": row.completion_hash,
        "status": row.status,
        "result_status": row.result_status,
        "credential_reference_stored": True,
        "upstream_file_content_proof_completed": True,
        "upstream_quarantine_staging_completed": True,
        "secret_resolution_performed": False,
        "provider_network_performed": False,
        "ssh_transport_performed": False,
        "host_key_verification_performed": False,
        "authentication_performed": False,
        "sftp_session_opened": False,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_stat_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_rename_performed": False,
        "remote_delete_performed": False,
        "command_executed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "storage_copy_performed": False,
        "checkpoint_created": True,
        "sync_executed": False,
        "credential_stored": False,
        "session_stored": False,
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
    "/profiles/{profile_id}/sftp-quarantine-staging-executions/{staging_id}/checkpoints",
    response_model=ExternalDocumentSourceSftpCheckpointRead,
    status_code=status.HTTP_201_CREATED,
)
def create_sftp_checkpoint_endpoint(
    profile_id: UUID,
    staging_id: UUID,
    payload: ExternalDocumentSourceSftpCheckpointRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCheckpointRead:
    try:
        row, outcome = create_external_document_source_sftp_checkpoint(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            quarantine_staging_id=staging_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_INITIAL_CHECKPOINT_RECORDED",
                entity_type="external_document_source_sftp_checkpoint",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-K recorded one immutable generation-1 checkpoint "
                    "from exact completed Phase 17.6-J quarantine custody using "
                    "persisted lineage only. No SFTP/provider I/O, object-store "
                    "I/O, Document creation, Evidence admission, processing, AI "
                    "or Claim mutation was performed."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpCheckpointRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-checkpoints/{checkpoint_id}",
    response_model=ExternalDocumentSourceSftpCheckpointRead,
)
def get_sftp_checkpoint_endpoint(
    profile_id: UUID,
    checkpoint_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpCheckpointRead:
    try:
        row = get_external_document_source_sftp_checkpoint(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            checkpoint_id=checkpoint_id,
        )
        return ExternalDocumentSourceSftpCheckpointRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-checkpoints/{checkpoint_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpCheckpointReceiptRead],
)
def list_sftp_checkpoint_receipts_endpoint(
    profile_id: UUID,
    checkpoint_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpCheckpointReceiptRead]:
    try:
        rows = list_external_document_source_sftp_checkpoint_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            checkpoint_id=checkpoint_id,
        )
        return [
            ExternalDocumentSourceSftpCheckpointReceiptRead.model_validate(row)
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
