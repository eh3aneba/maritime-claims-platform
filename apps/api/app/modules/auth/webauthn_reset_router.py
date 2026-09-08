from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, require_roles
from app.modules.auth.service import get_user_for_tenant
from app.modules.auth.webauthn_reset import (
    approve_webauthn_reset_request,
    cancel_webauthn_reset_request,
    create_webauthn_reset_request,
    execute_webauthn_reset_request,
    get_active_webauthn_credential_for_user,
    get_webauthn_reset_for_tenant,
    list_webauthn_resets,
    reject_webauthn_reset_request,
)
from app.modules.auth.webauthn_reset_schemas import (
    WebAuthnCredentialResetCreate,
    WebAuthnCredentialResetExecutionResult,
    WebAuthnCredentialResetRead,
    WebAuthnCredentialResetReject,
)
from app.modules.users.models import User, UserRole

router = APIRouter(
    prefix="/auth/webauthn-resets",
    tags=["authentication", "mfa", "webauthn", "enterprise-identity"],
)

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def _reset_or_404(
    db: Session,
    *,
    request_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
):
    reset = get_webauthn_reset_for_tenant(
        db,
        request_id=request_id,
        organization_id=organization_id,
        for_update=for_update,
    )
    if reset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WebAuthn credential reset request not found",
        )
    return reset


def _transition_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[WebAuthnCredentialResetRead])
def list_resets(
    db: Annotated[Session, Depends(get_db)],
    current_user: AdminUser,
) -> list[WebAuthnCredentialResetRead]:
    return [
        WebAuthnCredentialResetRead.model_validate(item)
        for item in list_webauthn_resets(db, organization_id=current_user.organization_id)
    ]


@router.post(
    "",
    response_model=WebAuthnCredentialResetRead,
    status_code=status.HTTP_201_CREATED,
)
def request_reset(
    payload: WebAuthnCredentialResetCreate,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> WebAuthnCredentialResetRead:
    target_user = get_user_for_tenant(
        db,
        user_id=payload.user_id,
        organization_id=current_user.organization_id,
    )
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found")
    credential = get_active_webauthn_credential_for_user(
        db,
        credential_id=payload.credential_id,
        organization_id=current_user.organization_id,
        user_id=target_user.id,
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active WebAuthn credential not found",
        )

    try:
        reset = create_webauthn_reset_request(
            db,
            target_user=target_user,
            credential=credential,
            requested_by=current_user,
            requested_auth_session=current_context.session,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="WEBAUTHN_CREDENTIAL_RESET_REQUESTED",
            entity_type="webauthn_credential_reset_request",
            entity_id=reset.id,
            new_values={
                "target_user_id": str(reset.user_id),
                "credential_id": str(reset.credential_id),
                "status": reset.status,
                "reason": reset.reason,
            },
        )
        db.commit()
        db.refresh(reset)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An open WebAuthn reset request already exists for this credential",
        ) from exc
    except (ValueError, PermissionError) as exc:
        db.rollback()
        raise _transition_error(exc) from exc
    return WebAuthnCredentialResetRead.model_validate(reset)


@router.post("/{request_id}/approve", response_model=WebAuthnCredentialResetRead)
def approve_reset(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> WebAuthnCredentialResetRead:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        approve_webauthn_reset_request(
            reset=reset,
            approved_by=current_user,
            approved_auth_session=current_context.session,
        )
    except (ValueError, PermissionError) as exc:
        db.rollback()
        raise _transition_error(exc) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="WEBAUTHN_CREDENTIAL_RESET_APPROVED",
        entity_type="webauthn_credential_reset_request",
        entity_id=reset.id,
        new_values={"status": reset.status, "target_user_id": str(reset.user_id)},
    )
    db.commit()
    db.refresh(reset)
    return WebAuthnCredentialResetRead.model_validate(reset)


@router.post("/{request_id}/reject", response_model=WebAuthnCredentialResetRead)
def reject_reset(
    request_id: UUID,
    payload: WebAuthnCredentialResetReject,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> WebAuthnCredentialResetRead:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        reject_webauthn_reset_request(
            reset=reset,
            rejected_by=current_user,
            rejected_auth_session=current_context.session,
            reason=payload.reason,
        )
    except (ValueError, PermissionError) as exc:
        db.rollback()
        raise _transition_error(exc) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="WEBAUTHN_CREDENTIAL_RESET_REJECTED",
        entity_type="webauthn_credential_reset_request",
        entity_id=reset.id,
        new_values={
            "status": reset.status,
            "target_user_id": str(reset.user_id),
            "rejection_reason": reset.rejection_reason,
        },
    )
    db.commit()
    db.refresh(reset)
    return WebAuthnCredentialResetRead.model_validate(reset)


@router.post("/{request_id}/cancel", response_model=WebAuthnCredentialResetRead)
def cancel_reset(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> WebAuthnCredentialResetRead:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        cancel_webauthn_reset_request(
            reset=reset,
            cancelled_by=current_user,
            cancelled_auth_session=current_context.session,
        )
    except (ValueError, PermissionError) as exc:
        db.rollback()
        raise _transition_error(exc) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="WEBAUTHN_CREDENTIAL_RESET_CANCELLED",
        entity_type="webauthn_credential_reset_request",
        entity_id=reset.id,
        new_values={"status": reset.status, "target_user_id": str(reset.user_id)},
    )
    db.commit()
    db.refresh(reset)
    return WebAuthnCredentialResetRead.model_validate(reset)


@router.post(
    "/{request_id}/execute",
    response_model=WebAuthnCredentialResetExecutionResult,
)
def execute_reset(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> WebAuthnCredentialResetExecutionResult:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        (
            reset,
            cancelled_registrations,
            cancelled_authentications,
            revoked_sessions,
            reenrollment_authorized,
        ) = execute_webauthn_reset_request(
            db,
            reset=reset,
            executed_by=current_user,
            executed_auth_session=current_context.session,
        )
    except (ValueError, PermissionError) as exc:
        db.rollback()
        raise _transition_error(exc) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="WEBAUTHN_CREDENTIAL_RESET_EXECUTED",
        entity_type="webauthn_credential_reset_request",
        entity_id=reset.id,
        new_values={
            "status": reset.status,
            "target_user_id": str(reset.user_id),
            "credential_id": str(reset.credential_id),
            "cancelled_registration_transactions": cancelled_registrations,
            "cancelled_authentication_transactions": cancelled_authentications,
            "revoked_sessions": revoked_sessions,
            "reenrollment_authorized": reenrollment_authorized,
            "reenrollment_expires_at": (
                reset.reenrollment_expires_at.isoformat()
                if reset.reenrollment_expires_at is not None
                else None
            ),
        },
    )
    db.commit()
    db.refresh(reset)
    return WebAuthnCredentialResetExecutionResult(
        request=WebAuthnCredentialResetRead.model_validate(reset),
        cancelled_registration_transactions=cancelled_registrations,
        cancelled_authentication_transactions=cancelled_authentications,
        revoked_sessions=revoked_sessions,
        reenrollment_authorized=reenrollment_authorized,
    )
