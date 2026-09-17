from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.evidence_admission_authorization_schemas import (
    ExternalDocumentSourceEvidenceAdmissionAuthorizationRead,
    ExternalDocumentSourceEvidenceAdmissionAuthorizationReceiptRead,
    ExternalDocumentSourceEvidenceAdmissionAuthorizationRequest,
)
from app.modules.external_document_sources.evidence_admission_authorization_service import (
    authorize_external_document_source_evidence_admission,
    get_external_document_source_evidence_admission_authorization,
    list_external_document_source_evidence_admission_authorization_receipts,
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


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "profile_id": str(authorization.profile_id),
        "generation_3_change_detection_execution_id": str(
            authorization.generation_3_change_detection_execution_id
        ),
        "checkpoint_generation_3_execution_id": str(
            authorization.checkpoint_generation_3_execution_id
        ),
        "provider_kind": authorization.provider_kind,
        "profile_hash": authorization.profile_hash,
        "authorized_projection_hash": authorization.authorized_projection_hash,
        "authorized_display_name_hash": authorization.authorized_display_name_hash,
        "authorized_version_token_hash": authorization.authorized_version_token_hash,
        "authorized_byte_size": authorization.authorized_byte_size,
        "authorized_mime_type_class": authorization.authorized_mime_type_class,
        "checkpoint_state_hash": authorization.checkpoint_state_hash,
        "checkpoint_completion_hash": authorization.checkpoint_completion_hash,
        "candidate_content_proof_hash": authorization.candidate_content_proof_hash,
        "candidate_completion_hash": authorization.candidate_completion_hash,
        "observation_completion_hash": authorization.observation_completion_hash,
        "scope_hash": authorization.scope_hash,
        "request_hash": authorization.request_hash,
        "authorization_hash": authorization.authorization_hash,
        "upstream_checkpoint_generation_3_advance_completed": True,
        "upstream_generation_3_change_detection_completed": True,
        "latest_generation_3_observation_confirmed": True,
        "remote_version_current_at_authorization": True,
        "human_authorization_recorded": True,
        "provider_client_constructed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "document_created": False,
        "evidence_admitted": False,
        "content_parsed": False,
        "content_extracted": False,
        "claim_mutated": False,
        "admission_execution_performed": False,
        "background_sync_started": False,
    }


@router.post(
    "/profiles/{profile_id}/generation-3-successor-change-detection-executions/{generation_3_change_detection_execution_id}/claims/{claim_id}/evidence-admission-authorizations",
    response_model=ExternalDocumentSourceEvidenceAdmissionAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_evidence_admission_endpoint(
    profile_id: UUID,
    generation_3_change_detection_execution_id: UUID,
    claim_id: UUID,
    payload: ExternalDocumentSourceEvidenceAdmissionAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceEvidenceAdmissionAuthorizationRead:
    try:
        authorization, outcome = authorize_external_document_source_evidence_admission(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            generation_3_change_detection_execution_id=generation_3_change_detection_execution_id,
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
                action="EXTERNAL_DOCUMENT_SOURCE_EVIDENCE_ADMISSION_AUTHORIZED",
                entity_type="external_document_source_evidence_admission_authorization",
                entity_id=authorization.id,
                new_values=_audit_values(authorization),
                details=(
                    "Phase 17.5-W recorded human authorization binding one exact current Phase-V generation-3 observation to one Claim. "
                    "No provider or object-storage I/O, Document creation, Evidence admission, parsing/OCR/indexing, Claim mutation, restaging, checkpoint advancement or background synchronization was performed."
                ),
            )
            db.commit()
            db.refresh(authorization)
        return ExternalDocumentSourceEvidenceAdmissionAuthorizationRead.model_validate(authorization)
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
    "/profiles/{profile_id}/evidence-admission-authorizations/{authorization_id}",
    response_model=ExternalDocumentSourceEvidenceAdmissionAuthorizationRead,
)
def get_evidence_admission_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceEvidenceAdmissionAuthorizationRead:
    try:
        authorization = get_external_document_source_evidence_admission_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        return ExternalDocumentSourceEvidenceAdmissionAuthorizationRead.model_validate(authorization)
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
    "/profiles/{profile_id}/evidence-admission-authorizations/{authorization_id}/receipts",
    response_model=list[ExternalDocumentSourceEvidenceAdmissionAuthorizationReceiptRead],
)
def list_evidence_admission_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceEvidenceAdmissionAuthorizationReceiptRead]:
    try:
        rows = list_external_document_source_evidence_admission_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        return [
            ExternalDocumentSourceEvidenceAdmissionAuthorizationReceiptRead.model_validate(row)
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
