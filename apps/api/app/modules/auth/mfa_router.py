from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext
from app.modules.auth.mfa import (
    confirm_totp_enrollment,
    get_current_totp_factor,
    get_totp_factor_for_user,
    revoke_totp_factor,
    start_totp_enrollment,
    verify_totp_for_session,
)
from app.modules.auth.schemas import (
    AuthSessionRead,
    TotpCodeRequest,
    TotpEnrollmentStartResponse,
    TotpFactorRead,
)

router = APIRouter(prefix="/auth/mfa/totp", tags=["authentication", "mfa"])


def _factor_or_404(
    db: Session,
    *,
    factor_id: UUID,
    current_context: CurrentAuthContext,
):
    factor = get_totp_factor_for_user(
        db,
        factor_id=factor_id,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
    )
    if factor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TOTP factor not found",
        )
    return factor


@router.post(
    "/enroll",
    response_model=TotpEnrollmentStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_enrollment(
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> TotpEnrollmentStartResponse:
    try:
        factor, secret, otpauth_uri = start_totp_enrollment(
            db,
            user=current_context.user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="TOTP_MFA_ENROLLMENT_STARTED",
        entity_type="totp_mfa_factor",
        entity_id=factor.id,
        new_values={
            "secret_fingerprint": factor.secret_fingerprint,
            "algorithm": factor.algorithm,
            "digits": factor.digits,
            "period_seconds": factor.period_seconds,
        },
    )
    db.commit()
    return TotpEnrollmentStartResponse(
        factor_id=factor.id,
        secret=secret,
        otpauth_uri=otpauth_uri,
        algorithm="SHA1",
        digits=factor.digits,
        period_seconds=factor.period_seconds,
    )


@router.get(
    "/factor",
    response_model=TotpFactorRead,
    response_model_exclude_none=True,
)
def current_factor(
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> TotpFactorRead:
    factor = get_current_totp_factor(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
    )
    if factor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TOTP factor not found",
        )
    return TotpFactorRead.model_validate(factor)


@router.post(
    "/{factor_id}/confirm",
    response_model=TotpFactorRead,
    response_model_exclude_none=True,
)
def confirm_enrollment(
    factor_id: UUID,
    payload: TotpCodeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> TotpFactorRead:
    factor = _factor_or_404(
        db,
        factor_id=factor_id,
        current_context=current_context,
    )
    try:
        confirm_totp_enrollment(factor=factor, code=payload.code)
    except ValueError as exc:
        code = status.HTTP_401_UNAUTHORIZED if "Invalid TOTP" in str(exc) else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="TOTP_MFA_ENROLLMENT_CONFIRMED",
        entity_type="totp_mfa_factor",
        entity_id=factor.id,
        new_values={"confirmed": True},
    )
    db.commit()
    db.refresh(factor)
    return TotpFactorRead.model_validate(factor)


@router.post(
    "/verify",
    response_model=AuthSessionRead,
    response_model_exclude_none=True,
)
def verify_current_session(
    payload: TotpCodeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> AuthSessionRead:
    factor = get_current_totp_factor(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
    )
    if factor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Active confirmed TOTP factor required",
        )
    try:
        verify_totp_for_session(
            factor=factor,
            auth_session=current_context.session,
            code=payload.code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="TOTP_MFA_SESSION_VERIFIED",
        entity_type="auth_session",
        entity_id=current_context.session.id,
        new_values={
            "mfa_method": "totp",
            "mfa_factor_id": str(factor.id),
        },
    )
    db.commit()
    db.refresh(current_context.session)
    return AuthSessionRead.model_validate(current_context.session)


@router.post(
    "/{factor_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_factor(
    factor_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> None:
    factor = _factor_or_404(
        db,
        factor_id=factor_id,
        current_context=current_context,
    )
    changed = revoke_totp_factor(
        factor=factor,
        revoked_by_id=current_context.user.id,
    )
    if changed:
        write_audit_log(
            db,
            organization_id=current_context.user.organization_id,
            user_id=current_context.user.id,
            action="TOTP_MFA_FACTOR_REVOKED",
            entity_type="totp_mfa_factor",
            entity_id=factor.id,
            new_values={"revoked": True, "reason": factor.revocation_reason},
        )
        db.commit()
    return None
