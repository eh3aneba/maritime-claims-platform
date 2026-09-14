from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.provider_client_activation_authorization_schemas import (
    ExternalDocumentSourceProviderClientActivationAuthorizationDecision,
    ExternalDocumentSourceProviderClientActivationAuthorizationRead,
    ExternalDocumentSourceProviderClientActivationAuthorizationReceiptRead,
    ExternalDocumentSourceProviderClientActivationAuthorizationRequest,
)
from app.modules.external_document_sources.provider_client_activation_authorization_service import (
    approve_external_document_source_provider_client_activation_authorization,
    get_external_document_source_provider_client_activation_authorization,
    list_external_document_source_provider_client_activation_authorization_receipts,
    reject_external_document_source_provider_client_activation_authorization,
    request_external_document_source_provider_client_activation_authorization,
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
        "health_qualification_id": str(row.health_qualification_id),
        "credential_reference_binding_id": str(row.credential_reference_binding_id),
        "provider_kind": row.provider_kind,
        "reference_backend": row.reference_backend,
        "health_result_status": row.health_result_status,
        "scope_hash": row.scope_hash,
        "execution_limit": row.execution_limit,
        "status": row.status,
        "provider_client_activation_authorized": row.provider_client_activation_authorized,
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": False,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "oauth_token_exchanged": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_network_performed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "subscription_created": False,
        "checkpoint_created": False,
        "sync_executed": False,
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


def _commit_expiry_if_needed(db: Session, *, current_user, row, outcome: str) -> None:
    if outcome != "expired":
        return
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="EXTERNAL_DOCUMENT_SOURCE_PROVIDER_CLIENT_ACTIVATION_AUTHORIZATION_EXPIRED",
        entity_type="external_document_source_provider_client_activation_authorization",
        entity_id=row.id,
        new_values=_audit_values(row) | {"terminal_hash": row.terminal_hash},
        details="Bounded provider-client activation authority expired without provider execution.",
    )
    db.commit()
    db.refresh(row)


@router.post(
    "/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}/provider-client-activation-authorizations",
    response_model=ExternalDocumentSourceProviderClientActivationAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_provider_client_activation_authorization_endpoint(
    profile_id: UUID,
    qualification_id: UUID,
    payload: ExternalDocumentSourceProviderClientActivationAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceProviderClientActivationAuthorizationRead:
    try:
        row, outcome = request_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            health_qualification_id=qualification_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
        )
        if outcome == "requested":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_PROVIDER_CLIENT_ACTIVATION_AUTHORIZATION_REQUESTED",
                entity_type="external_document_source_provider_client_activation_authorization",
                entity_id=row.id,
                new_values=_audit_values(row) | {"request_hash": row.request_hash},
                details="Provider-client activation authorization requested; no credential resolution, OAuth, provider network, remote document, Evidence, Document or claim authority was exercised.",
            )
            db.commit()
            db.refresh(row)
        else:
            _commit_expiry_if_needed(db, current_user=current_user, row=row, outcome=outcome)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProviderClientActivationAuthorizationRead.model_validate(row)


@router.post(
    "/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/approve",
    response_model=ExternalDocumentSourceProviderClientActivationAuthorizationRead,
)
def approve_provider_client_activation_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceProviderClientActivationAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceProviderClientActivationAuthorizationRead:
    try:
        row, outcome = approve_external_document_source_provider_client_activation_authorization(
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
                action="EXTERNAL_DOCUMENT_SOURCE_PROVIDER_CLIENT_ACTIVATION_AUTHORIZATION_APPROVED",
                entity_type="external_document_source_provider_client_activation_authorization",
                entity_id=row.id,
                new_values=_audit_values(row)
                | {
                    "authorization_hash": row.authorization_hash,
                    "authorization_expires_at": row.authorization_expires_at.isoformat() if row.authorization_expires_at else None,
                },
                details="Independent second approval granted one short-lived later provider-client activation authority only; OAuth and provider traffic remain disabled.",
            )
            db.commit()
            db.refresh(row)
        else:
            _commit_expiry_if_needed(db, current_user=current_user, row=row, outcome=outcome)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProviderClientActivationAuthorizationRead.model_validate(row)


@router.post(
    "/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/reject",
    response_model=ExternalDocumentSourceProviderClientActivationAuthorizationRead,
)
def reject_provider_client_activation_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceProviderClientActivationAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceProviderClientActivationAuthorizationRead:
    try:
        row, outcome = reject_external_document_source_provider_client_activation_authorization(
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
                action="EXTERNAL_DOCUMENT_SOURCE_PROVIDER_CLIENT_ACTIVATION_AUTHORIZATION_REJECTED",
                entity_type="external_document_source_provider_client_activation_authorization",
                entity_id=row.id,
                new_values=_audit_values(row) | {"terminal_hash": row.terminal_hash},
                details="Provider-client activation authorization rejected without provider execution.",
            )
            db.commit()
            db.refresh(row)
        else:
            _commit_expiry_if_needed(db, current_user=current_user, row=row, outcome=outcome)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProviderClientActivationAuthorizationRead.model_validate(row)


@router.get(
    "/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}",
    response_model=ExternalDocumentSourceProviderClientActivationAuthorizationRead,
)
def get_provider_client_activation_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceProviderClientActivationAuthorizationRead:
    try:
        row, outcome = get_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        _commit_expiry_if_needed(db, current_user=current_user, row=row, outcome=outcome)
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceProviderClientActivationAuthorizationRead.model_validate(row)


@router.get(
    "/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/receipts",
    response_model=list[ExternalDocumentSourceProviderClientActivationAuthorizationReceiptRead],
)
def list_provider_client_activation_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceProviderClientActivationAuthorizationReceiptRead]:
    try:
        receipts, outcome = list_external_document_source_provider_client_activation_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
        if outcome == "expired":
            row, _ = get_external_document_source_provider_client_activation_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
            _commit_expiry_if_needed(db, current_user=current_user, row=row, outcome="expired")
            receipts, _ = list_external_document_source_provider_client_activation_authorization_receipts(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
    except (ExternalDocumentSourceValidationError, ExternalDocumentSourceConflictError, ExternalDocumentSourceNotFoundError, IntegrityError, ValueError) as exc:
        db.rollback()
        _raise_service_error(exc)
    return [ExternalDocumentSourceProviderClientActivationAuthorizationReceiptRead.model_validate(receipt) for receipt in receipts]
