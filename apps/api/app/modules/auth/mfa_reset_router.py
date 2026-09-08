from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, require_roles
from app.modules.auth.mfa import get_totp_factor_for_user
from app.modules.auth.mfa_reset import (
    approve_reset_request,
    cancel_reset_request,
    create_reset_request,
    execute_reset_request,
    get_reset_request_for_tenant,
    list_reset_requests,
    reject_reset_request,
)
from app.modules.auth.mfa_reset_schemas import (
    MfaFactorResetCreate,
    MfaFactorResetExecutionResult,
    MfaFactorResetRead,
    MfaFactorResetReject,
)
from app.modules.auth.service import get_user_for_tenant
from app.modules.users.models import User, UserRole

router = APIRouter(
    prefix="/auth/mfa-resets",
    tags=["authentication", "mfa", "enterprise-identity"],
)

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def _reset_or_404(
    db: Session,
    *,
    request_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
):
    reset = get_reset_request_for_tenant(
        db,
        request_id=request_id,
        organization_id=organization_id,
        for_update=for_update,
    )
    if reset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MFA factor reset request not found",
        )
    return reset


def _transition_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[MfaFactorResetRead])
def list_resets(
    db: Annotated[Session, Depends(get_db)],
    current_user: AdminUser,
) -> list[MfaFactorResetRead]:
    return [
        MfaFactorResetRead.model_validate(item)
        for item in list_reset_requests(db, organization_id=current_user.organization_id)
    ]


@router.post(
    "",
    response_model=MfaFactorResetRead,
    status_code=status.HTTP_201_CREATED,
)
def request_reset(
    payload: MfaFactorResetCreate,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> MfaFactorResetRead:
    target_user = get_user_for_tenant(
        db,
        user_id=payload.user_id,
        organization_id=current_user.organization_id,
    )
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found")
    factor = get_totp_factor_for_user(
        db,
        factor_id=payload.factor_id,
        organization_id=current_user.organization_id,
        user_id=target_user.id,
    )
    if factor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TOTP factor not found")

    try:
        reset = create_reset_request(
            db,
            target_user=target_user,
            factor=factor,
            requested_by=current_user,
            requested_auth_session=current_context.session,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="MFA_FACTOR_RESET_REQUESTED",
            entity_type="mfa_factor_reset_request",
            entity_id=reset.id,
            new_values={
                "target_user_id": str(reset.user_id),
                "factor_id": str(reset.factor_id),
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
            detail="An open reset request already exists for this factor",
        ) from exc
    except (ValueError, PermissionError) as exc:
        db.rollback()
        raise _transition_error(exc) from exc
    return MfaFactorResetRead.model_validate(reset)


@router.post("/{request_id}/approve", response_model=MfaFactorResetRead)
def approve_reset(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> MfaFactorResetRead:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        approve_reset_request(
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
        action="MFA_FACTOR_RESET_APPROVED",
        entity_type="mfa_factor_reset_request",
        entity_id=reset.id,
        new_values={"status": reset.status, "target_user_id": str(reset.user_id)},
    )
    db.commit()
    db.refresh(reset)
    return MfaFactorResetRead.model_validate(reset)


@router.post("/{request_id}/reject", response_model=MfaFactorResetRead)
def reject_reset(
    request_id: UUID,
    payload: MfaFactorResetReject,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> MfaFactorResetRead:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        reject_reset_request(
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
        action="MFA_FACTOR_RESET_REJECTED",
        entity_type="mfa_factor_reset_request",
        entity_id=reset.id,
        new_values={
            "status": reset.status,
            "target_user_id": str(reset.user_id),
            "rejection_reason": reset.rejection_reason,
        },
    )
    db.commit()
    db.refresh(reset)
    return MfaFactorResetRead.model_validate(reset)


@router.post("/{request_id}/cancel", response_model=MfaFactorResetRead)
def cancel_reset(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> MfaFactorResetRead:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        cancel_reset_request(
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
        action="MFA_FACTOR_RESET_CANCELLED",
        entity_type="mfa_factor_reset_request",
        entity_id=reset.id,
        new_values={"status": reset.status, "target_user_id": str(reset.user_id)},
    )
    db.commit()
    db.refresh(reset)
    return MfaFactorResetRead.model_validate(reset)


@router.post(
    "/{request_id}/execute",
    response_model=MfaFactorResetExecutionResult,
)
def execute_reset(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: AdminUser,
) -> MfaFactorResetExecutionResult:
    reset = _reset_or_404(
        db,
        request_id=request_id,
        organization_id=current_user.organization_id,
        for_update=True,
    )
    try:
        reset, invalidated_codes, revoked_sessions = execute_reset_request(
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
        action="MFA_FACTOR_RESET_EXECUTED",
        entity_type="mfa_factor_reset_request",
        entity_id=reset.id,
        new_values={
            "status": reset.status,
            "target_user_id": str(reset.user_id),
            "factor_id": str(reset.factor_id),
            "invalidated_recovery_codes": invalidated_codes,
            "revoked_sessions": revoked_sessions,
        },
    )
    db.commit()
    db.refresh(reset)
    return MfaFactorResetExecutionResult(
        request=MfaFactorResetRead.model_validate(reset),
        invalidated_recovery_codes=invalidated_codes,
        revoked_sessions=revoked_sessions,
    )
