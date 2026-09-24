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
from app.modules.external_document_sources.sftp_handshake_authorization_schemas import (
    ExternalDocumentSourceSftpHandshakeAuthorizationDecision,
    ExternalDocumentSourceSftpHandshakeAuthorizationRead,
    ExternalDocumentSourceSftpHandshakeAuthorizationReceiptRead,
    ExternalDocumentSourceSftpHandshakeAuthorizationRequest,
)
from app.modules.external_document_sources.sftp_handshake_authorization_service import (
    approve_external_document_source_sftp_handshake_authorization,
    get_external_document_source_sftp_handshake_authorization,
    list_external_document_source_sftp_handshake_authorization_receipts,
    reject_external_document_source_sftp_handshake_authorization,
    request_external_document_source_sftp_handshake_authorization,
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
        "health_qualification_id": str(row.health_qualification_id),
        "credential_reference_binding_id": str(
            row.credential_reference_binding_id
        ),
        "provider_kind": "sftp",
        "authentication_kind": row.authentication_kind,
        "reference_backend": row.reference_backend,
        "health_result_status": row.health_result_status,
        "scope_hash": row.scope_hash,
        "execution_limit": row.execution_limit,
        "status": row.status,
        "sftp_handshake_authorized": row.sftp_handshake_authorized,
        "credential_reference_stored": True,
        "secret_resolution_performed": False,
        "credential_stored": False,
        "provider_network_performed": False,
        "authentication_performed": False,
        "sftp_session_opened": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


def _commit_expiry_if_needed(
    db: Session,
    *,
    current_user,
    row,
    outcome: str,
) -> None:
    if outcome != "expired":
        return
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="EXTERNAL_DOCUMENT_SOURCE_SFTP_HANDSHAKE_AUTHORIZATION_EXPIRED",
        entity_type="external_document_source_sftp_handshake_authorization",
        entity_id=row.id,
        new_values=_audit_values(row) | {"terminal_hash": row.terminal_hash},
        details=(
            "Bounded SFTP handshake authorization expired without DNS, "
            "network, SSH/SFTP session or remote-file execution."
        ),
    )
    db.commit()
    db.refresh(row)


@router.post(
    "/profiles/{profile_id}/sftp-credential-health-qualifications/"
    "{qualification_id}/handshake-authorizations",
    response_model=ExternalDocumentSourceSftpHandshakeAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_sftp_handshake_authorization_endpoint(
    profile_id: UUID,
    qualification_id: UUID,
    payload: ExternalDocumentSourceSftpHandshakeAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpHandshakeAuthorizationRead:
    try:
        row, outcome = (
            request_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                health_qualification_id=qualification_id,
                requested_by_id=current_user.id,
                request_key=payload.request_key,
                request_reason=payload.reason,
            )
        )
        if outcome == "requested":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=(
                    "EXTERNAL_DOCUMENT_SOURCE_SFTP_HANDSHAKE_AUTHORIZATION_REQUESTED"
                ),
                entity_type=(
                    "external_document_source_sftp_handshake_authorization"
                ),
                entity_id=row.id,
                new_values=_audit_values(row)
                | {"request_hash": row.request_hash},
                details=(
                    "One bounded future SFTP handshake authorization was "
                    "requested; no secret resolution, DNS/network activity, "
                    "SSH/SFTP session or remote-file authority was exercised."
                ),
            )
            db.commit()
            db.refresh(row)
        else:
            _commit_expiry_if_needed(
                db,
                current_user=current_user,
                row=row,
                outcome=outcome,
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
    return ExternalDocumentSourceSftpHandshakeAuthorizationRead.model_validate(
        row
    )


@router.post(
    "/profiles/{profile_id}/sftp-handshake-authorizations/"
    "{authorization_id}/approve",
    response_model=ExternalDocumentSourceSftpHandshakeAuthorizationRead,
)
def approve_sftp_handshake_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceSftpHandshakeAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpHandshakeAuthorizationRead:
    try:
        row, outcome = (
            approve_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                approved_by_id=current_user.id,
                decision_reason=payload.reason,
            )
        )
        if outcome == "authorized":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=(
                    "EXTERNAL_DOCUMENT_SOURCE_SFTP_HANDSHAKE_AUTHORIZATION_APPROVED"
                ),
                entity_type=(
                    "external_document_source_sftp_handshake_authorization"
                ),
                entity_id=row.id,
                new_values=_audit_values(row)
                | {
                    "authorization_hash": row.authorization_hash,
                    "authorization_expires_at": (
                        row.authorization_expires_at.isoformat()
                        if row.authorization_expires_at
                        else None
                    ),
                },
                details=(
                    "Independent second approval granted one short-lived "
                    "future SFTP handshake authority only; no network or "
                    "remote-file execution occurred."
                ),
            )
            db.commit()
            db.refresh(row)
        else:
            _commit_expiry_if_needed(
                db,
                current_user=current_user,
                row=row,
                outcome=outcome,
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
    return ExternalDocumentSourceSftpHandshakeAuthorizationRead.model_validate(
        row
    )


@router.post(
    "/profiles/{profile_id}/sftp-handshake-authorizations/"
    "{authorization_id}/reject",
    response_model=ExternalDocumentSourceSftpHandshakeAuthorizationRead,
)
def reject_sftp_handshake_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    payload: ExternalDocumentSourceSftpHandshakeAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpHandshakeAuthorizationRead:
    try:
        row, outcome = (
            reject_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                rejected_by_id=current_user.id,
                decision_reason=payload.reason,
            )
        )
        if outcome == "rejected":
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=(
                    "EXTERNAL_DOCUMENT_SOURCE_SFTP_HANDSHAKE_AUTHORIZATION_REJECTED"
                ),
                entity_type=(
                    "external_document_source_sftp_handshake_authorization"
                ),
                entity_id=row.id,
                new_values=_audit_values(row)
                | {"terminal_hash": row.terminal_hash},
                details=(
                    "SFTP handshake authorization rejected without network "
                    "or remote-file execution."
                ),
            )
            db.commit()
            db.refresh(row)
        else:
            _commit_expiry_if_needed(
                db,
                current_user=current_user,
                row=row,
                outcome=outcome,
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
    return ExternalDocumentSourceSftpHandshakeAuthorizationRead.model_validate(
        row
    )


@router.get(
    "/profiles/{profile_id}/sftp-handshake-authorizations/"
    "{authorization_id}",
    response_model=ExternalDocumentSourceSftpHandshakeAuthorizationRead,
)
def get_sftp_handshake_authorization_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> ExternalDocumentSourceSftpHandshakeAuthorizationRead:
    try:
        row, outcome = (
            get_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
        )
        _commit_expiry_if_needed(
            db,
            current_user=current_user,
            row=row,
            outcome=outcome,
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
    return ExternalDocumentSourceSftpHandshakeAuthorizationRead.model_validate(
        row
    )


@router.get(
    "/profiles/{profile_id}/sftp-handshake-authorizations/"
    "{authorization_id}/receipts",
    response_model=list[
        ExternalDocumentSourceSftpHandshakeAuthorizationReceiptRead
    ],
)
def list_sftp_handshake_authorization_receipts_endpoint(
    profile_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ConnectionAuthorizationAdminMfa,
) -> list[ExternalDocumentSourceSftpHandshakeAuthorizationReceiptRead]:
    try:
        rows, outcome = (
            list_external_document_source_sftp_handshake_authorization_receipts(
                db,
                organization_id=current_user.organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
            )
        )
        if outcome == "expired":
            row, _ = (
                get_external_document_source_sftp_handshake_authorization(
                    db,
                    organization_id=current_user.organization_id,
                    profile_id=profile_id,
                    authorization_id=authorization_id,
                )
            )
            _commit_expiry_if_needed(
                db,
                current_user=current_user,
                row=row,
                outcome="expired",
            )
            rows, _ = (
                list_external_document_source_sftp_handshake_authorization_receipts(
                    db,
                    organization_id=current_user.organization_id,
                    profile_id=profile_id,
                    authorization_id=authorization_id,
                )
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
    return [
        ExternalDocumentSourceSftpHandshakeAuthorizationReceiptRead.model_validate(
            row
        )
        for row in rows
    ]
