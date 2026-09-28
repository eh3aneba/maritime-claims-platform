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
from app.modules.external_document_sources.sftp_evidence_admission_authorization_schemas import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead,
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceiptRead,
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRequest,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_service import (
    authorize_external_document_source_sftp_evidence_admission,
    get_external_document_source_sftp_evidence_admission_authorization,
    list_external_document_source_sftp_evidence_admission_authorization_receipts,
)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _audit_values(row) -> dict:
    return {
        "claim_id": str(row.claim_id),
        "profile_id": str(row.profile_id),
        "generation3_change_detection_id": str(row.generation3_change_detection_id),
        "generation3_checkpoint_advancement_id": str(row.generation3_checkpoint_advancement_id),
        "generation3_restaging_id": str(row.generation3_restaging_id),
        "provider_kind": row.provider_kind,
        "profile_hash": row.profile_hash,
        "authorized_projection_hash": row.authorized_projection_hash,
        "authorized_entry_hash": row.authorized_entry_hash,
        "authorized_relative_path_hash": row.authorized_relative_path_hash,
        "authorized_byte_size": row.authorized_byte_size,
        "authorized_modified_at": (
            row.authorized_modified_at.isoformat()
            if row.authorized_modified_at is not None
            else None
        ),
        "authorized_metadata_id_hash": row.authorized_metadata_id_hash,
        "authorized_content_sha256": row.authorized_content_sha256,
        "authorized_storage_object_key_hash": row.authorized_storage_object_key_hash,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "checkpoint_state_hash": row.checkpoint_state_hash,
        "checkpoint_completion_hash": row.checkpoint_completion_hash,
        "candidate_content_proof_hash": row.candidate_content_proof_hash,
        "candidate_completion_hash": row.candidate_completion_hash,
        "observation_completion_hash": row.observation_completion_hash,
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "authorization_hash": row.authorization_hash,
        **{
            field: bool(getattr(row, field))
            for field in (
                "upstream_generation3_checkpoint_completed",
                "upstream_generation3_observation_completed",
                "latest_generation3_observation_confirmed",
                "remote_version_current_at_authorization",
                "human_authorization_recorded",
                "credential_stored",
                "session_stored",
                "provider_network_performed",
                "ssh_transport_performed",
                "authentication_performed",
                "sftp_session_opened",
                "remote_content_transiently_observed",
                "remote_list_performed",
                "remote_stat_performed",
                "remote_read_performed",
                "remote_write_performed",
                "storage_read_performed",
                "storage_write_performed",
                "storage_reconciliation_performed",
                "durable_content_staged",
                "checkpoint_created",
                "checkpoint_advanced",
                "document_created",
                "evidence_admitted",
                "content_parsed",
                "content_extracted",
                "processing_enqueued",
                "ai_executed",
                "claim_mutated",
                "background_sync_started",
            )
        },
    }


@router.post(
    "/profiles/{profile_id}/sftp-generation-3-change-detections/{execution_id}/claims/{claim_id}/evidence-admission-authorizations",
    response_model=ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_sftp_evidence_admission_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    claim_id: UUID,
    payload: ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead:
    try:
        authorization, outcome = authorize_external_document_source_sftp_evidence_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            generation3_change_detection_id=execution_id,
            claim_id=claim_id,
            authorized_by_id=current_user.id,
            request_key=payload.request_key,
            authorization_reason=payload.reason,
        )
        if outcome == "authorized":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_SFTP_EVIDENCE_ADMISSION_AUTHORIZED",
                entity_type="external_document_source_sftp_evidence_admission_authorization",
                entity_id=authorization.id,
                new_values=_audit_values(authorization),
                details=(
                    "Phase 17.6-S recorded human authorization binding one latest exact "
                    "integrity-valid Phase-R unchanged SFTP generation-3 observation to one "
                    "Claim. No SFTP/provider or object-storage I/O, Document/Evidence creation, "
                    "processing, AI, Claim mutation, restaging, checkpoint advancement or "
                    "background synchronization was performed."
                ),
            )
            db.commit()
            db.refresh(authorization)
        return ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead.model_validate(
            authorization
        )
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
    "/profiles/{profile_id}/sftp-evidence-admission-authorizations/{authorization_id}",
    response_model=ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead,
)
def get_sftp_evidence_admission_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead:
    try:
        authorization = get_external_document_source_sftp_evidence_admission_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        return ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead.model_validate(
            authorization
        )
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
    "/profiles/{profile_id}/sftp-evidence-admission-authorizations/{authorization_id}/receipts",
    response_model=list[ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceiptRead],
)
def list_sftp_evidence_admission_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceiptRead]:
    try:
        rows = list_external_document_source_sftp_evidence_admission_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        return [
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceiptRead.model_validate(row)
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
