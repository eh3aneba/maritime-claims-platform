from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, enforce_mfa_policy_for_context, require_roles
from app.modules.external_document_sources.schemas import (
    ExternalDocumentSourceProfileDecision,
    ExternalDocumentSourceProfileRead,
    ExternalDocumentSourceProfileReceiptRead,
    ExternalDocumentSourceProfileRequest,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    approve_external_document_source_profile,
    disable_external_document_source_profile,
    get_external_document_source_profile,
    list_external_document_source_profile_receipts,
    list_external_document_source_profiles,
    reject_external_document_source_profile,
    request_external_document_source_profile,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/external-document-sources", tags=["external-document-sources"])


def require_external_document_source_admin_mfa(
    context: CurrentAuthContext,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if context.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    enforce_mfa_policy_for_context(db, context=context)
    return context.user


ExternalDocumentSourceAdminMfa = Annotated[User, Depends(require_external_document_source_admin_mfa)]
ExternalDocumentSourceReader = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/profiles", response_model=ExternalDocumentSourceProfileRead, status_code=status.HTTP_201_CREATED)
def request_profile_endpoint(
    payload: ExternalDocumentSourceProfileRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceAdminMfa,
) -> ExternalDocumentSourceProfileRead:
    try:
        profile = request_external_document_source_profile(
            db,
            organization_id=current_user.organization_id,
            requested_by_id=current_user.id,
            provider_kind=payload.provider_kind,
            display_name=payload.display_name,
            raw_config=payload.config,
            request_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EXTERNAL_DOCUMENT_SOURCE_PROFILE_REQUESTED",
            entity_type="external_document_source_profile",
            entity_id=profile.id,
            new_values={
                "provider_kind": profile.provider_kind,
                "config_hash": profile.config_hash,
                "profile_hash": profile.profile_hash,
                "status": profile.status,
                "live_connection_authorized": False,
                "credential_stored": False,
                "remote_read_performed": False,
                "evidence_admitted": False,
            },
        )
        db.commit()
        db.refresh(profile)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProfileRead.model_validate(profile)


@router.post("/profiles/{profile_id}/approve", response_model=ExternalDocumentSourceProfileRead)
def approve_profile_endpoint(
    profile_id: UUID,
    payload: ExternalDocumentSourceProfileDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceAdminMfa,
) -> ExternalDocumentSourceProfileRead:
    try:
        profile, outcome = approve_external_document_source_profile(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            approved_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_PROFILE_APPROVED",
                entity_type="external_document_source_profile",
                entity_id=profile.id,
                new_values={"status": profile.status, "approval_hash": profile.approval_hash, "live_connection_authorized": False},
            )
            db.commit()
            db.refresh(profile)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProfileRead.model_validate(profile)


@router.post("/profiles/{profile_id}/reject", response_model=ExternalDocumentSourceProfileRead)
def reject_profile_endpoint(
    profile_id: UUID,
    payload: ExternalDocumentSourceProfileDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceAdminMfa,
) -> ExternalDocumentSourceProfileRead:
    try:
        profile, outcome = reject_external_document_source_profile(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            rejected_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_PROFILE_REJECTED",
                entity_type="external_document_source_profile",
                entity_id=profile.id,
                new_values={"status": profile.status, "terminal_hash": profile.terminal_hash, "live_connection_authorized": False},
            )
            db.commit()
            db.refresh(profile)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProfileRead.model_validate(profile)


@router.post("/profiles/{profile_id}/disable", response_model=ExternalDocumentSourceProfileRead)
def disable_profile_endpoint(
    profile_id: UUID,
    payload: ExternalDocumentSourceProfileDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceAdminMfa,
) -> ExternalDocumentSourceProfileRead:
    try:
        profile, outcome = disable_external_document_source_profile(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            disabled_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_PROFILE_DISABLED",
                entity_type="external_document_source_profile",
                entity_id=profile.id,
                new_values={"status": profile.status, "terminal_hash": profile.terminal_hash, "live_connection_authorized": False},
            )
            db.commit()
            db.refresh(profile)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProfileRead.model_validate(profile)


@router.get("/profiles", response_model=list[ExternalDocumentSourceProfileRead])
def list_profiles_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceReader,
    provider_kind: str | None = None,
) -> list[ExternalDocumentSourceProfileRead]:
    try:
        profiles = list_external_document_source_profiles(db, organization_id=current_user.organization_id, provider_kind=provider_kind)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)
    return [ExternalDocumentSourceProfileRead.model_validate(profile) for profile in profiles]


@router.get("/profiles/{profile_id}", response_model=ExternalDocumentSourceProfileRead)
def get_profile_endpoint(
    profile_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceReader,
) -> ExternalDocumentSourceProfileRead:
    try:
        profile = get_external_document_source_profile(db, organization_id=current_user.organization_id, profile_id=profile_id)
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)
    return ExternalDocumentSourceProfileRead.model_validate(profile)


@router.get("/profiles/{profile_id}/receipts", response_model=list[ExternalDocumentSourceProfileReceiptRead])
def list_profile_receipts_endpoint(
    profile_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ExternalDocumentSourceReader,
) -> list[ExternalDocumentSourceProfileReceiptRead]:
    try:
        receipts = list_external_document_source_profile_receipts(db, organization_id=current_user.organization_id, profile_id=profile_id)
    except (ExternalDocumentSourceNotFoundError, ExternalDocumentSourceConflictError) as exc:
        _raise_service_error(exc)
    return [ExternalDocumentSourceProfileReceiptRead.model_validate(receipt) for receipt in receipts]
