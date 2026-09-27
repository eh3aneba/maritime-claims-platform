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
from app.modules.external_document_sources.sftp_generation3_restaging_schemas import (
    ExternalDocumentSourceSftpGeneration3RestagingRead,
    ExternalDocumentSourceSftpGeneration3RestagingReceiptRead,
    ExternalDocumentSourceSftpGeneration3RestagingRequest,
)
from app.modules.external_document_sources.sftp_generation3_restaging_service import (
    execute_external_document_source_sftp_generation3_restaging,
    get_external_document_source_sftp_generation3_restaging,
    list_external_document_source_sftp_generation3_restaging_receipts,
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
        "successor_change_detection_id": str(row.successor_change_detection_id),
        "checkpoint_advancement_id": str(row.checkpoint_advancement_id),
        "successor_restaging_id": str(row.successor_restaging_id),
        "predecessor_checkpoint_id": str(row.predecessor_checkpoint_id),
        "change_detection_id": str(row.change_detection_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "successor_checkpoint_state_hash": row.successor_checkpoint_state_hash,
        "successor_checkpoint_completion_hash": row.successor_checkpoint_completion_hash,
        "predecessor_content_sha256": row.predecessor_content_sha256,
        "predecessor_content_byte_count": row.predecessor_content_byte_count,
        "predecessor_storage_object_key_hash": row.predecessor_storage_object_key_hash,
        "predecessor_candidate_completion_hash": row.predecessor_candidate_completion_hash,
        "successor_change_scope_hash": row.successor_change_scope_hash,
        "successor_change_request_hash": row.successor_change_request_hash,
        "successor_change_completion_hash": row.successor_change_completion_hash,
        "observed_projection_hash": row.observed_projection_hash,
        "observed_byte_size": row.observed_byte_size,
        "observed_modified_at": row.observed_modified_at.isoformat() if row.observed_modified_at else None,
        "observed_metadata_id_hash": row.observed_metadata_id_hash,
        "listing_entry_hash": row.listing_entry_hash,
        "read_operation_kind": row.read_operation_kind,
        "read_policy_hash": row.read_policy_hash,
        "read_adapter_kind": row.read_adapter_kind,
        "candidate_generation": row.candidate_generation,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "status": row.status,
        "result_status": row.result_status,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        "content_authentication_method": row.content_authentication_method,
        "content_latency_class": row.content_latency_class,
        "content_proof_hash": row.content_proof_hash,
        "completion_hash": row.completion_hash,
        **{
            field: bool(getattr(row, field))
            for field in (
                "credential_reference_stored", "upstream_predecessor_checkpoint_completed",
                "upstream_change_detection_completed", "upstream_successor_restaging_completed",
                "upstream_checkpoint_advancement_completed", "upstream_successor_change_detection_completed",
                "successor_content_proof_completed", "secret_resolution_performed",
                "provider_network_performed", "ssh_transport_performed",
                "host_key_verification_performed", "host_key_verified",
                "authentication_performed", "authentication_succeeded",
                "sftp_session_opened", "sftp_session_closed",
                "remote_content_transiently_observed", "remote_read_performed",
                "storage_read_performed", "storage_write_performed",
                "storage_reconciliation_performed", "durable_content_staged",
                "remote_content_stored", "generation3_restaging_completed",
                "credential_stored", "session_stored", "raw_response_stored",
                "remote_content_returned", "remote_content_logged",
                "content_parsed", "content_extracted", "remote_list_performed",
                "remote_stat_performed", "remote_write_performed",
                "remote_rename_performed", "remote_delete_performed",
                "remote_mkdir_performed", "remote_chmod_performed",
                "remote_chown_performed", "remote_touch_performed",
                "command_executed", "storage_delete_performed",
                "storage_copy_performed", "checkpoint_created",
                "checkpoint_advanced", "subscription_created", "evidence_admitted",
                "document_created", "processing_enqueued", "ai_executed",
                "claim_mutated",
            )
        },
    }


@router.post(
    "/profiles/{profile_id}/sftp-successor-change-detections/{successor_change_detection_id}/generation-3-restaging-executions",
    response_model=ExternalDocumentSourceSftpGeneration3RestagingRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_generation3_restaging_endpoint(
    profile_id: UUID,
    successor_change_detection_id: UUID,
    payload: ExternalDocumentSourceSftpGeneration3RestagingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpGeneration3RestagingRead:
    try:
        row, outcome = execute_external_document_source_sftp_generation3_restaging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            successor_change_detection_id=successor_change_detection_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_GENERATION3_SUCCESSOR_STAGED",
                entity_type="external_document_source_sftp_generation3_restaging",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-P consumed one exact Phase 17.6-O changed observation, "
                    "re-read only the lineage-derived exact SFTP file, committed a durable "
                    "generation-3 content proof before object-store PUT, and reconciled one "
                    "immutable generation-3 quarantine candidate. The Phase 17.6-N generation-2 "
                    "checkpoint and Phase 17.6-M object remain unchanged. No directory listing, "
                    "checkpoint advancement, Document/Evidence admission, processing, AI, "
                    "Claim mutation, remote mutation, storage overwrite/delete/copy, raw storage "
                    "key, credential, remote path or file body is exposed."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpGeneration3RestagingRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-generation-3-restaging-executions/{restaging_id}",
    response_model=ExternalDocumentSourceSftpGeneration3RestagingRead,
)
def get_sftp_generation3_restaging_endpoint(
    profile_id: UUID,
    restaging_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpGeneration3RestagingRead:
    try:
        row = get_external_document_source_sftp_generation3_restaging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            restaging_id=restaging_id,
        )
        return ExternalDocumentSourceSftpGeneration3RestagingRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-generation-3-restaging-executions/{restaging_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpGeneration3RestagingReceiptRead],
)
def list_sftp_generation3_restaging_receipts_endpoint(
    profile_id: UUID,
    restaging_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpGeneration3RestagingReceiptRead]:
    try:
        rows = list_external_document_source_sftp_generation3_restaging_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            restaging_id=restaging_id,
        )
        return [
            ExternalDocumentSourceSftpGeneration3RestagingReceiptRead.model_validate(row)
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
