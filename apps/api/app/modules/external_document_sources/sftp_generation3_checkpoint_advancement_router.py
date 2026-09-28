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
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_schemas import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead,
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceiptRead,
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRequest,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_service import (
    execute_external_document_source_sftp_generation3_checkpoint_advancement,
    get_external_document_source_sftp_generation3_checkpoint_advancement,
    list_external_document_source_sftp_generation3_checkpoint_advancement_receipts,
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
        "generation3_restaging_id": str(row.generation3_restaging_id),
        "predecessor_checkpoint_advancement_id": str(row.predecessor_checkpoint_advancement_id),
        "successor_change_detection_id": str(row.successor_change_detection_id),
        "predecessor_successor_restaging_id": str(row.predecessor_successor_restaging_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "predecessor_checkpoint_generation": row.predecessor_checkpoint_generation,
        "predecessor_checkpoint_state_hash": row.predecessor_checkpoint_state_hash,
        "predecessor_checkpoint_completion_hash": row.predecessor_checkpoint_completion_hash,
        "candidate_scope_hash": row.candidate_scope_hash,
        "candidate_request_hash": row.candidate_request_hash,
        "candidate_content_proof_hash": row.candidate_content_proof_hash,
        "candidate_completion_hash": row.candidate_completion_hash,
        "candidate_generation": row.candidate_generation,
        "observation_scope_hash": row.observation_scope_hash,
        "observation_completion_hash": row.observation_completion_hash,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "successor_checkpoint_kind": row.successor_checkpoint_kind,
        "successor_checkpoint_generation": row.successor_checkpoint_generation,
        "successor_checkpoint_state_hash": row.successor_checkpoint_state_hash,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completion_hash": row.completion_hash,
        "status": row.status,
        "result_status": row.result_status,
        **{
            field: bool(getattr(row, field))
            for field in (
                "credential_reference_stored", "upstream_checkpoint_completed",
                "upstream_successor_change_detection_completed",
                "upstream_generation3_restaging_completed", "secret_resolution_performed",
                "provider_network_performed", "ssh_transport_performed",
                "host_key_verification_performed", "authentication_performed",
                "sftp_session_opened", "remote_content_transiently_observed",
                "remote_list_performed", "remote_stat_performed", "remote_read_performed",
                "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
                "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
                "remote_touch_performed", "command_executed", "storage_read_performed",
                "storage_write_performed", "storage_reconciliation_performed",
                "storage_delete_performed", "storage_copy_performed", "durable_content_staged",
                "checkpoint_created", "checkpoint_advanced", "credential_stored", "session_stored",
                "raw_response_stored", "remote_content_stored", "remote_content_returned",
                "remote_content_logged", "content_parsed", "content_extracted",
                "evidence_admitted", "document_created", "processing_enqueued",
                "ai_executed", "claim_mutated",
            )
        },
    }


@router.post(
    "/profiles/{profile_id}/sftp-generation-3-restaging-executions/{restaging_id}/checkpoint-advancements",
    response_model=ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_generation3_checkpoint_advancement_endpoint(
    profile_id: UUID,
    restaging_id: UUID,
    payload: ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead:
    try:
        row, outcome = execute_external_document_source_sftp_generation3_checkpoint_advancement(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            generation3_restaging_id=restaging_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_GENERATION3_CHECKPOINT_ADVANCED",
                entity_type="external_document_source_sftp_generation3_checkpoint_advancement",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-Q advanced control-plane SFTP checkpoint custody from the exact "
                    "Phase 17.6-N generation-2 checkpoint to the integrity-valid Phase 17.6-P "
                    "generation-3 candidate using persisted lineage only. No SFTP or object-store "
                    "I/O, content observation, checkpoint-side restaging, Document/Evidence admission, "
                    "processing, AI, Claim mutation, raw storage key, ETag, remote path, credential "
                    "or file body was authorized or exposed."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-generation3-checkpoint-advancements/{advancement_id}",
    response_model=ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead,
)
def get_sftp_generation3_checkpoint_advancement_endpoint(
    profile_id: UUID,
    advancement_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead:
    try:
        row = get_external_document_source_sftp_generation3_checkpoint_advancement(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            advancement_id=advancement_id,
        )
        return ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-generation3-checkpoint-advancements/{advancement_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceiptRead],
)
def list_sftp_generation3_checkpoint_advancement_receipts_endpoint(
    profile_id: UUID,
    advancement_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceiptRead]:
    try:
        rows = list_external_document_source_sftp_generation3_checkpoint_advancement_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            advancement_id=advancement_id,
        )
        return [
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceiptRead.model_validate(row)
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
