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
from app.modules.external_document_sources.sftp_directory_listing_schemas import (
    ExternalDocumentSourceSftpDirectoryListingRead,
    ExternalDocumentSourceSftpDirectoryListingReceiptRead,
    ExternalDocumentSourceSftpDirectoryListingRequest,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    create_external_document_source_sftp_directory_listing,
    get_external_document_source_sftp_directory_listing,
    list_external_document_source_sftp_directory_listing_receipts,
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


def _serialize(row, entries) -> ExternalDocumentSourceSftpDirectoryListingRead:
    payload = {
        field: getattr(row, field)
        for field in ExternalDocumentSourceSftpDirectoryListingRead.model_fields
        if field != "entries"
    }
    payload["entries"] = entries
    return ExternalDocumentSourceSftpDirectoryListingRead.model_validate(payload)


def _audit_values(row) -> dict:
    return {
        "profile_id": str(row.profile_id),
        "session_activation_id": str(row.session_activation_id),
        "credential_reference_binding_id": str(row.credential_reference_binding_id),
        "provider_kind": row.provider_kind,
        "destination_hostname": row.destination_hostname,
        "destination_port": row.destination_port,
        "remote_root_path_hash": row.remote_root_path_hash,
        "request_relative_path": row.request_relative_path,
        "listing_adapter_kind": row.listing_adapter_kind,
        "result_status": row.result_status,
        "failure_code": row.failure_code,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "entry_count": row.entry_count,
        "page_count": row.page_count,
        "truncated": row.truncated,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "items_hash": row.items_hash,
        "result_hash": row.result_hash,
        "credential_reference_stored": True,
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
        "remote_list_performed": row.remote_list_performed,
        "remote_stat_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_rename_performed": False,
        "remote_delete_performed": False,
        "command_executed": False,
        "checkpoint_created": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/sftp-session-activations/{activation_id}/directory-listings",
    response_model=ExternalDocumentSourceSftpDirectoryListingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_sftp_directory_listing_endpoint(
    profile_id: UUID,
    activation_id: UUID,
    payload: ExternalDocumentSourceSftpDirectoryListingRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpDirectoryListingRead:
    try:
        row, entries, outcome = create_external_document_source_sftp_directory_listing(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            session_activation_id=activation_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
            relative_path=payload.relative_path,
        )
        if outcome == "completed":
            listed = row.result_status == "listed"
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=(
                    "EXTERNAL_DOCUMENT_SOURCE_SFTP_DIRECTORY_METADATA_LISTED"
                    if listed
                    else "EXTERNAL_DOCUMENT_SOURCE_SFTP_DIRECTORY_LISTING_FAILED"
                ),
                entity_type="external_document_source_sftp_directory_listing",
                entity_id=row.id,
                new_values=_audit_values(row),
                details=(
                    "Phase 17.6-H transiently revalidated the approved SFTP lineage and listed one bounded "
                    "non-recursive metadata page within the approved root, then immediately closed the session. "
                    "No stat, file-content read, remote mutation, command, checkpoint, Evidence, Document, "
                    "processing, AI or Claim authority was exercised."
                    if listed
                    else
                    "Phase 17.6-H failed closed with a bounded sanitized directory-listing result and no "
                    "file-content, mutation, command or downstream claim authority."
                ),
            )
        db.commit()
        db.refresh(row)
        return _serialize(row, entries)
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
    "/profiles/{profile_id}/sftp-directory-listings/{listing_id}",
    response_model=ExternalDocumentSourceSftpDirectoryListingRead,
)
def get_sftp_directory_listing_endpoint(
    profile_id: UUID,
    listing_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpDirectoryListingRead:
    try:
        row, entries = get_external_document_source_sftp_directory_listing(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            listing_id=listing_id,
        )
        return _serialize(row, entries)
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/sftp-directory-listings/{listing_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpDirectoryListingReceiptRead],
)
def list_sftp_directory_listing_receipts_endpoint(
    profile_id: UUID,
    listing_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpDirectoryListingReceiptRead]:
    try:
        return list_external_document_source_sftp_directory_listing_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            listing_id=listing_id,
        )
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)
