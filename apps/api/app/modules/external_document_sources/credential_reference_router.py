from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.connection_authorization_router import ConnectionAuthorizationAdminMfa, router
from app.modules.external_document_sources.credential_reference_schemas import (
    ExternalDocumentSourceCredentialReferenceDecision,
    ExternalDocumentSourceCredentialReferenceRead,
    ExternalDocumentSourceCredentialReferenceReceiptRead,
    ExternalDocumentSourceCredentialReferenceRequest,
)
from app.modules.external_document_sources.credential_reference_service import (
    approve_external_document_source_credential_reference,
    disable_external_document_source_credential_reference,
    get_external_document_source_credential_reference,
    list_external_document_source_credential_reference_receipts,
    reject_external_document_source_credential_reference,
    request_external_document_source_credential_reference,
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


def _audit_values(binding) -> dict:
    return {
        "profile_id": str(binding.profile_id),
        "bootstrap_execution_id": str(binding.bootstrap_execution_id),
        "provider_kind": binding.provider_kind,
        "reference_backend": binding.reference_backend,
        "locator_hash": binding.locator_hash,
        "scope_hash": binding.scope_hash,
        "status": binding.status,
        "credential_reference_stored": True,
        "credential_stored": False,
        "oauth_token_exchanged": False,
        "provider_network_performed": False,
        "remote_read_performed": False,
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


@router.post(
    "/profiles/{profile_id}/bootstrap-executions/{execution_id}/credential-reference-bindings",
    response_model=ExternalDocumentSourceCredentialReferenceRead,
    status_code=status.HTTP_201_CREATED,
)
def request_credential_reference_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    payload: ExternalDocumentSourceCredentialReferenceRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialReferenceRead:
    try:
        binding, outcome = request_external_document_source_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            bootstrap_execution_id=execution_id,
            requested_by_id=current_user.id,
            request_key=payload.request_key,
            request_reason=payload.reason,
            reference_backend=payload.reference_backend,
            reference_namespace=payload.reference_namespace,
            reference_name=payload.reference_name,
            reference_version=payload.reference_version,
        )
        if outcome == "requested":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CREDENTIAL_REFERENCE_REQUESTED",
                entity_type="external_document_source_credential_reference_binding",
                entity_id=binding.id,
                new_values=_audit_values(binding),
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceCredentialReferenceRead.model_validate(binding)


@router.post(
    "/profiles/{profile_id}/credential-reference-bindings/{binding_id}/approve",
    response_model=ExternalDocumentSourceCredentialReferenceRead,
)
def approve_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceCredentialReferenceDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialReferenceRead:
    try:
        binding, outcome = approve_external_document_source_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            approved_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "approved":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CREDENTIAL_REFERENCE_APPROVED",
                entity_type="external_document_source_credential_reference_binding",
                entity_id=binding.id,
                new_values={**_audit_values(binding), "approval_hash": binding.approval_hash},
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceCredentialReferenceRead.model_validate(binding)


@router.post(
    "/profiles/{profile_id}/credential-reference-bindings/{binding_id}/reject",
    response_model=ExternalDocumentSourceCredentialReferenceRead,
)
def reject_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceCredentialReferenceDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialReferenceRead:
    try:
        binding, outcome = reject_external_document_source_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            rejected_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "rejected":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CREDENTIAL_REFERENCE_REJECTED",
                entity_type="external_document_source_credential_reference_binding",
                entity_id=binding.id,
                new_values={**_audit_values(binding), "terminal_hash": binding.terminal_hash},
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceCredentialReferenceRead.model_validate(binding)


@router.post(
    "/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
    response_model=ExternalDocumentSourceCredentialReferenceRead,
)
def disable_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceCredentialReferenceDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialReferenceRead:
    try:
        binding, outcome = disable_external_document_source_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            disabled_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome == "disabled":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="EXTERNAL_DOCUMENT_SOURCE_CREDENTIAL_REFERENCE_DISABLED",
                entity_type="external_document_source_credential_reference_binding",
                entity_id=binding.id,
                new_values={**_audit_values(binding), "terminal_hash": binding.terminal_hash},
            )
            db.commit()
            db.refresh(binding)
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
    return ExternalDocumentSourceCredentialReferenceRead.model_validate(binding)


@router.get(
    "/profiles/{profile_id}/credential-reference-bindings/{binding_id}",
    response_model=ExternalDocumentSourceCredentialReferenceRead,
)
def get_credential_reference_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceCredentialReferenceRead:
    try:
        binding = get_external_document_source_credential_reference(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
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
    return ExternalDocumentSourceCredentialReferenceRead.model_validate(binding)


@router.get(
    "/profiles/{profile_id}/credential-reference-bindings/{binding_id}/receipts",
    response_model=list[ExternalDocumentSourceCredentialReferenceReceiptRead],
)
def list_credential_reference_receipts_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceCredentialReferenceReceiptRead]:
    try:
        receipts = list_external_document_source_credential_reference_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
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
    return [ExternalDocumentSourceCredentialReferenceReceiptRead.model_validate(receipt) for receipt in receipts]
