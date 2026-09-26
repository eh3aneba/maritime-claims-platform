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
from app.modules.external_document_sources.sftp_quarantine_staging_schemas import (
    ExternalDocumentSourceSftpQuarantineStagingRead,
    ExternalDocumentSourceSftpQuarantineStagingReceiptRead,
    ExternalDocumentSourceSftpQuarantineStagingRequest,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    execute_external_document_source_sftp_quarantine_staging,
    get_external_document_source_sftp_quarantine_staging,
    list_external_document_source_sftp_quarantine_staging_receipts,
)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc


def _audit_values(row) -> dict:
    return {
        "profile_id": str(row.profile_id),
        "file_content_proof_id": str(row.file_content_proof_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "session_activation_id": str(row.session_activation_id),
        "credential_reference_binding_id": str(
            row.credential_reference_binding_id
        ),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "listing_entry_hash": row.listing_entry_hash,
        "upstream_scope_hash": row.upstream_scope_hash,
        "upstream_request_hash": row.upstream_request_hash,
        "upstream_result_hash": row.upstream_result_hash,
        "read_adapter_kind": row.read_adapter_kind,
        "expected_content_sha256": row.expected_content_sha256,
        "expected_content_byte_count": row.expected_content_byte_count,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completion_hash": row.completion_hash,
        "status": row.status,
        "result_status": row.result_status,
        "credential_reference_stored": True,
        "upstream_file_content_proof_completed": True,
        "secret_resolution_performed": row.secret_resolution_performed,
        "credential_stored": False,
        "provider_network_performed": row.provider_network_performed,
        "ssh_transport_performed": row.ssh_transport_performed,
        "host_key_verification_performed": row.host_key_verification_performed,
        "host_key_verified": row.host_key_verified,
        "authentication_performed": row.authentication_performed,
        "authentication_succeeded": row.authentication_succeeded,
        "sftp_session_opened": row.sftp_session_opened,
        "sftp_session_closed": row.sftp_session_closed,
        "remote_content_transiently_observed": row.remote_content_transiently_observed,
        "remote_read_performed": row.remote_read_performed,
        "storage_reconciliation_performed": row.storage_reconciliation_performed,
        "durable_content_staged": row.durable_content_staged,
        "remote_content_stored": row.remote_content_stored,
        "session_stored": False,
        "raw_response_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "remote_list_performed": False,
        "remote_stat_performed": False,
        "remote_write_performed": False,
        "remote_rename_performed": False,
        "remote_delete_performed": False,
        "remote_mkdir_performed": False,
        "remote_chmod_performed": False,
        "remote_chown_performed": False,
        "remote_touch_performed": False,
        "command_executed": False,
        "storage_delete_performed": False,
        "storage_copy_performed": False,
        "checkpoint_created": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/sftp-file-content-proofs/{proof_id}/quarantine-staging-executions",
    response_model=ExternalDocumentSourceSftpQuarantineStagingRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_sftp_quarantine_staging_endpoint(
    profile_id: UUID,
    proof_id: UUID,
    payload: ExternalDocumentSourceSftpQuarantineStagingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpQuarantineStagingRead:
    try:
        row, outcome = execute_external_document_source_sftp_quarantine_staging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            file_content_proof_id=proof_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_QUARANTINE_STAGED",
                entity_type="external_document_source_sftp_quarantine_staging",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-J re-read the exact Phase I-bound SFTP file, "
                    "required SHA-256 and byte-count equality, then reconciled "
                    "the exact bytes into governed non-destructive quarantine "
                    "storage. The object remains non-Document and non-Evidence. "
                    "No raw storage key/URL/credential, remote body/session, "
                    "provider mutation, storage delete/copy, checkpoint, "
                    "processing, AI or Claim authority was exposed or exercised."
                ),
            )
            db.commit()
            db.refresh(row)
        return ExternalDocumentSourceSftpQuarantineStagingRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-quarantine-staging-executions/{staging_id}",
    response_model=ExternalDocumentSourceSftpQuarantineStagingRead,
)
def get_sftp_quarantine_staging_endpoint(
    profile_id: UUID,
    staging_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpQuarantineStagingRead:
    try:
        row = get_external_document_source_sftp_quarantine_staging(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            staging_id=staging_id,
        )
        return ExternalDocumentSourceSftpQuarantineStagingRead.model_validate(row)
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
    "/profiles/{profile_id}/sftp-quarantine-staging-executions/{staging_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpQuarantineStagingReceiptRead],
)
def list_sftp_quarantine_staging_receipts_endpoint(
    profile_id: UUID,
    staging_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpQuarantineStagingReceiptRead]:
    try:
        rows = list_external_document_source_sftp_quarantine_staging_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            staging_id=staging_id,
        )
        return [
            ExternalDocumentSourceSftpQuarantineStagingReceiptRead.model_validate(
                row
            )
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
