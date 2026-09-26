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
from app.modules.external_document_sources.sftp_file_content_proof_schemas import (
    ExternalDocumentSourceSftpFileContentProofRead,
    ExternalDocumentSourceSftpFileContentProofReceiptRead,
    ExternalDocumentSourceSftpFileContentProofRequest,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    create_external_document_source_sftp_file_content_proof,
    get_external_document_source_sftp_file_content_proof,
    list_external_document_source_sftp_file_content_proof_receipts,
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


def _audit_values(row) -> dict:
    return {
        "profile_id": str(row.profile_id),
        "directory_listing_id": str(row.directory_listing_id),
        "listing_entry_id": str(row.listing_entry_id),
        "session_activation_id": str(row.session_activation_id),
        "credential_reference_binding_id": str(row.credential_reference_binding_id),
        "provider_kind": row.provider_kind,
        "listing_entry_hash": row.listing_entry_hash,
        "declared_byte_size": row.declared_byte_size,
        "read_adapter_kind": row.read_adapter_kind,
        "read_limit": row.read_limit,
        "max_content_bytes": row.max_content_bytes,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "result_hash": row.result_hash,
        "result_status": row.result_status,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        "credential_reference_stored": True,
        "secret_resolution_performed": True,
        "credential_stored": False,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": True,
        "authentication_performed": True,
        "authentication_succeeded": True,
        "sftp_session_opened": True,
        "sftp_session_closed": True,
        "remote_content_transiently_observed": True,
        "remote_read_performed": True,
        "session_stored": False,
        "raw_response_stored": False,
        "remote_content_stored": False,
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
        "checkpoint_created": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/sftp-directory-listings/{listing_id}/entries/{entry_id}/file-content-proofs",
    response_model=ExternalDocumentSourceSftpFileContentProofRead,
    status_code=status.HTTP_201_CREATED,
)
def create_sftp_file_content_proof_endpoint(
    profile_id: UUID,
    listing_id: UUID,
    entry_id: UUID,
    payload: ExternalDocumentSourceSftpFileContentProofRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpFileContentProofRead:
    try:
        row, outcome = create_external_document_source_sftp_file_content_proof(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            directory_listing_id=listing_id,
            listing_entry_id=entry_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "completed":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_FILE_CONTENT_PROOF_VERIFIED",
                entity_type="external_document_source_sftp_file_content_proof",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-I transiently reconnected through the exact governed SFTP lineage, "
                    "read exactly one previously listed file under an 8 MiB bound, persisted only SHA-256 "
                    "and byte-count proof, discarded the remote bytes before persistence/return, and exercised "
                    "no remote mutation, staging, checkpoint, Document, Evidence, processing, AI or Claim authority."
                ),
            )
        db.commit()
        db.refresh(row)
        return ExternalDocumentSourceSftpFileContentProofRead.model_validate(row)
    except (
        ExternalDocumentSourceNotFoundError,
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/sftp-file-content-proofs/{proof_id}",
    response_model=ExternalDocumentSourceSftpFileContentProofRead,
)
def get_sftp_file_content_proof_endpoint(
    profile_id: UUID,
    proof_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpFileContentProofRead:
    try:
        return ExternalDocumentSourceSftpFileContentProofRead.model_validate(
            get_external_document_source_sftp_file_content_proof(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                proof_id=proof_id,
            )
        )
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/sftp-file-content-proofs/{proof_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpFileContentProofReceiptRead],
)
def list_sftp_file_content_proof_receipts_endpoint(
    profile_id: UUID,
    proof_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpFileContentProofReceiptRead]:
    try:
        rows = list_external_document_source_sftp_file_content_proof_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            proof_id=proof_id,
        )
        return [ExternalDocumentSourceSftpFileContentProofReceiptRead.model_validate(row) for row in rows]
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)
