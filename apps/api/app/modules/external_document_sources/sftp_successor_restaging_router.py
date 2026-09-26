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
from app.modules.external_document_sources.sftp_successor_restaging_schemas import (
    ExternalDocumentSourceSftpSuccessorRestagingRead,
    ExternalDocumentSourceSftpSuccessorRestagingReceiptRead,
    ExternalDocumentSourceSftpSuccessorRestagingRequest,
)
from app.modules.external_document_sources.sftp_successor_restaging_service import (
    execute_external_document_source_sftp_successor_restaging,
    get_external_document_source_sftp_successor_restaging,
    list_external_document_source_sftp_successor_restaging_receipts,
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
        "change_detection_id": str(row.change_detection_id),
        "checkpoint_id": str(row.checkpoint_id),
        "quarantine_staging_id": str(row.quarantine_staging_id),
        "file_content_proof_id": str(row.file_content_proof_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "checkpoint_state_hash": row.checkpoint_state_hash,
        "checkpoint_completion_hash": row.checkpoint_completion_hash,
        "predecessor_content_sha256": row.predecessor_content_sha256,
        "predecessor_content_byte_count": row.predecessor_content_byte_count,
        "change_scope_hash": row.change_scope_hash,
        "change_request_hash": row.change_request_hash,
        "change_completion_hash": row.change_completion_hash,
        "observed_projection_hash": row.observed_projection_hash,
        "observed_byte_size": row.observed_byte_size,
        "listing_entry_hash": row.listing_entry_hash,
        "read_operation_kind": row.read_operation_kind,
        "read_policy_hash": row.read_policy_hash,
        "read_adapter_kind": row.read_adapter_kind,
        "successor_generation": row.successor_generation,
        "successor_content_sha256": row.successor_content_sha256,
        "successor_content_byte_count": row.successor_content_byte_count,
        "successor_content_proof_hash": row.successor_content_proof_hash,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completion_hash": row.completion_hash,
        "status": row.status,
        "result_status": row.result_status,
        **{field: bool(getattr(row, field)) for field in (
            "credential_reference_stored", "upstream_checkpoint_completed",
            "upstream_change_detection_completed", "successor_content_proof_completed",
            "secret_resolution_performed", "credential_stored", "session_stored",
            "provider_network_performed", "ssh_transport_performed",
            "host_key_verification_performed", "host_key_verified",
            "authentication_performed", "authentication_succeeded",
            "sftp_session_opened", "sftp_session_closed",
            "remote_content_transiently_observed", "remote_read_performed",
            "storage_write_performed", "storage_read_performed", "storage_reconciliation_performed",
            "durable_content_staged", "raw_response_stored",
            "remote_content_stored", "remote_content_returned",
            "remote_content_logged", "content_parsed", "content_extracted",
            "remote_list_performed", "remote_stat_performed",
            "remote_write_performed", "remote_rename_performed",
            "remote_delete_performed", "remote_mkdir_performed",
            "remote_chmod_performed", "remote_chown_performed",
            "remote_touch_performed", "command_executed",
            "storage_delete_performed", "storage_copy_performed",
            "checkpoint_advanced", "evidence_admitted", "document_created",
            "processing_enqueued", "ai_executed", "claim_mutated",
        )},
    }


@router.post(
    "/profiles/{profile_id}/sftp-change-detections/{change_detection_id}/successor-restaging-executions",
    response_model=ExternalDocumentSourceSftpSuccessorRestagingRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_successor_restaging_endpoint(
    profile_id: UUID,
    change_detection_id: UUID,
    payload: ExternalDocumentSourceSftpSuccessorRestagingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpSuccessorRestagingRead:
    try:
        row, outcome = execute_external_document_source_sftp_successor_restaging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            change_detection_id=change_detection_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_CHANGED_FILE_SUCCESSOR_STAGED",
                entity_type="external_document_source_sftp_successor_restaging",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-M re-read only the exact Phase 17.6-L changed SFTP file, "
                    "proved a bounded successor digest/byte count distinct from the current "
                    "checkpoint, and reconciled one immutable candidate successor object. "
                    "The Phase 17.6-K checkpoint was not advanced. No Document/Evidence, "
                    "processing, AI, Claim mutation, remote mutation, storage delete/copy, "
                    "raw key, URL, credential or file body was exposed."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpSuccessorRestagingRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-successor-restaging-executions/{restaging_id}",
    response_model=ExternalDocumentSourceSftpSuccessorRestagingRead,
)
def get_sftp_successor_restaging_endpoint(
    profile_id: UUID,
    restaging_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpSuccessorRestagingRead:
    try:
        row = get_external_document_source_sftp_successor_restaging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            restaging_id=restaging_id,
        )
        return ExternalDocumentSourceSftpSuccessorRestagingRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-successor-restaging-executions/{restaging_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpSuccessorRestagingReceiptRead],
)
def list_sftp_successor_restaging_receipts_endpoint(
    profile_id: UUID,
    restaging_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpSuccessorRestagingReceiptRead]:
    try:
        rows = list_external_document_source_sftp_successor_restaging_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            restaging_id=restaging_id,
        )
        return [
            ExternalDocumentSourceSftpSuccessorRestagingReceiptRead.model_validate(row)
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
