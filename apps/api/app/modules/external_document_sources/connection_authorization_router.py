from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, enforce_mfa_policy_for_context
from app.modules.external_document_sources.connection_authorization_schemas import (
    ExternalDocumentSourceConnectionAuthorizationDecision,
    ExternalDocumentSourceConnectionAuthorizationRead,
    ExternalDocumentSourceConnectionAuthorizationReceiptRead,
    ExternalDocumentSourceConnectionAuthorizationRequest,
)
from app.modules.external_document_sources.connection_authorization_service import (
    approve_external_document_source_connection_authorization,
    get_external_document_source_connection_authorization,
    list_external_document_source_connection_authorization_receipts,
    reject_external_document_source_connection_authorization,
    request_external_document_source_connection_authorization,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User, UserRole

router = APIRouter()


def require_external_document_source_connection_admin_mfa(
    context: CurrentAuthContext,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if context.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    enforce_mfa_policy_for_context(db, context=context)
    return context.user


ConnectionAuthorizationAdminMfa = Annotated[User, Depends(require_external_document_source_connection_admin_mfa)]


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _commit_expiry_if_needed(
    db: Session,
    *,
    current_user: User,
    authorization,
    outcome: str,
) -> None:
    if outcome != "expired":
        return
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="EXTERNAL_DOCUMENT_SOURCE_CONNECTION_AUTHORIZATION_EXPIRED",
        entity_type="external_document_source_connection_authorization",
        entity_id=authorization.id,
        new_values={
            "status": authorization.status,
            "terminal_hash": authorization.terminal_hash,
            "live_connection_authorized": False,
            "oauth_token_exchanged": False,
            "remote_read_performed": False,
            "evidence_admitted": False,
        },
    )
    db.commit()
    db.refresh(authorization)


@router.post(
    "/profiles/{profile_id}/discoveries/{run_id}/connection-authorizations",
    response_model=ExternalDocumentSourceConnectionAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_connection_authorization_endpoint(
    profile_id: UUID,
    run_id: UUID,
    payload: ExternalDocumentSourceConnectionAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceConnectionAuthorizationRead:
    try:
        authorization, outcome = request_external_document_source_connection_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            discovery_run_id=run_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "requested":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CONNECTION_AUTHORIZATION_REQUESTED",
                entity_type="external_document_source_connection_authorization",
                entity_id=authorization.id,
                new_values={
                    "profile_id": str(authorization.profile_id),
                    "discovery_run_id": str(authorization.discovery_run_id),
                    "scope_hash": authorization.scope_hash,
                    "request_hash": authorization.request_hash,
                    "execution_limit": authorization.execution_limit,
                    "status": authorization.status,
                    "live_connection_authorized": False,
                    "credential_stored": False,
                    "oauth_token_exchanged": False,
                    "remote_read_performed": False,
                    "evidence_admitted": False,
                },
            )
            db.commit()
            db.refresh(authorization)
        else:
            _commit_expiry_if_needed(db, current_user=current_user, authorization=authorization, outcome=outcome)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceConnectionAuthorizationRead.model_validate(authorization)


@router.post(
    "/profiles/{profile_id}/connection-authorizations/{authorization_id}/approve",
    response_model=ExternalDocumentSourceConnectionAuthorizationRead,
)
def approve_connection_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceConnectionAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceConnectionAuthorizationRead:
    try:
        authorization, outcome = approve_external_document_source_connection_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            approved_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "authorized":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CONNECTION_AUTHORIZATION_APPROVED",
                entity_type="external_document_source_connection_authorization",
                entity_id=authorization.id,
                new_values={
                    "status": authorization.status,
                    "authorization_hash": authorization.authorization_hash,
                    "authorization_expires_at": authorization.authorization_expires_at.isoformat()
                    if authorization.authorization_expires_at
                    else None,
                    "execution_limit": authorization.execution_limit,
                    "live_connection_authorized": True,
                    "credential_stored": False,
                    "oauth_token_exchanged": False,
                    "remote_read_performed": False,
                    "evidence_admitted": False,
                },
            )
            db.commit()
            db.refresh(authorization)
        else:
            _commit_expiry_if_needed(db, current_user=current_user, authorization=authorization, outcome=outcome)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceConnectionAuthorizationRead.model_validate(authorization)


@router.post(
    "/profiles/{profile_id}/connection-authorizations/{authorization_id}/reject",
    response_model=ExternalDocumentSourceConnectionAuthorizationRead,
)
def reject_connection_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceConnectionAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceConnectionAuthorizationRead:
    try:
        authorization, outcome = reject_external_document_source_connection_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            rejected_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "rejected":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CONNECTION_AUTHORIZATION_REJECTED",
                entity_type="external_document_source_connection_authorization",
                entity_id=authorization.id,
                new_values={
                    "status": authorization.status,
                    "terminal_hash": authorization.terminal_hash,
                    "live_connection_authorized": False,
                    "credential_stored": False,
                    "oauth_token_exchanged": False,
                    "remote_read_performed": False,
                    "evidence_admitted": False,
                },
            )
            db.commit()
            db.refresh(authorization)
        else:
            _commit_expiry_if_needed(db, current_user=current_user, authorization=authorization, outcome=outcome)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceConnectionAuthorizationRead.model_validate(authorization)


@router.get(
    "/profiles/{profile_id}/connection-authorizations/{authorization_id}",
    response_model=ExternalDocumentSourceConnectionAuthorizationRead,
)
def get_connection_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceConnectionAuthorizationRead:
    try:
        authorization, outcome = get_external_document_source_connection_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        _commit_expiry_if_needed(db, current_user=current_user, authorization=authorization, outcome=outcome)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceConnectionAuthorizationRead.model_validate(authorization)


@router.get(
    "/profiles/{profile_id}/connection-authorizations/{authorization_id}/receipts",
    response_model=list[ExternalDocumentSourceConnectionAuthorizationReceiptRead],
)
def list_connection_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceConnectionAuthorizationReceiptRead]:
    try:
        receipts, outcome = list_external_document_source_connection_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        if outcome == "expired":
            authorization, _ = get_external_document_source_connection_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
            _commit_expiry_if_needed(db, current_user=current_user, authorization=authorization, outcome="expired")
            receipts, _ = list_external_document_source_connection_authorization_receipts(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
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
    return [ExternalDocumentSourceConnectionAuthorizationReceiptRead.model_validate(receipt) for receipt in receipts]
