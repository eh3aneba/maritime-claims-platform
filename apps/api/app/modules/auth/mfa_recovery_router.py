from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext
from app.modules.auth.mfa import get_current_totp_factor
from app.modules.auth.mfa_recovery import (
    RECOVERY_CODE_COUNT,
    regenerate_recovery_codes,
    verify_recovery_code_for_session,
)
from app.modules.auth.mfa_recovery_schemas import (
    MfaRecoveryCodeBatchResponse,
    MfaRecoveryCodeVerifyRequest,
)
from app.modules.auth.schemas import AuthSessionRead

router = APIRouter(
    prefix="/auth/mfa/recovery-codes",
    tags=["authentication", "mfa"],
)


def _active_confirmed_factor_or_409(
    db: Session,
    *,
    current_context: CurrentAuthContext,
):
    factor = get_current_totp_factor(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
    )
    if factor is None or factor.confirmed_at is None or factor.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active confirmed TOTP factor required",
        )
    return factor


@router.post(
    "/regenerate",
    response_model=MfaRecoveryCodeBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def regenerate_current_recovery_codes(
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> MfaRecoveryCodeBatchResponse:
    factor = _active_confirmed_factor_or_409(
        db,
        current_context=current_context,
    )
    try:
        batch_id, recovery_codes, invalidated_count = regenerate_recovery_codes(
            db,
            user=current_context.user,
            factor=factor,
            auth_session=current_context.session,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "mfa_verification_required",
                "message": "MFA verification is required for the current authentication session",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="MFA_RECOVERY_CODES_REGENERATED",
        entity_type="totp_mfa_factor",
        entity_id=factor.id,
        new_values={
            "batch_id": str(batch_id),
            "count": RECOVERY_CODE_COUNT,
            "invalidated_unused_count": invalidated_count,
        },
    )
    db.commit()
    return MfaRecoveryCodeBatchResponse(
        factor_id=factor.id,
        batch_id=batch_id,
        recovery_codes=recovery_codes,
        count=RECOVERY_CODE_COUNT,
    )


@router.post(
    "/verify",
    response_model=AuthSessionRead,
    response_model_exclude_none=True,
)
def verify_current_session_with_recovery_code(
    payload: MfaRecoveryCodeVerifyRequest,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> AuthSessionRead:
    factor = _active_confirmed_factor_or_409(
        db,
        current_context=current_context,
    )
    try:
        _, recovery_code = verify_recovery_code_for_session(
            db,
            factor=factor,
            auth_session=current_context.session,
            code=payload.code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid recovery code",
        ) from exc

    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="MFA_RECOVERY_CODE_SESSION_VERIFIED",
        entity_type="auth_session",
        entity_id=current_context.session.id,
        new_values={
            "mfa_method": "recovery_code",
            "mfa_factor_id": str(factor.id),
            "recovery_batch_id": str(recovery_code.batch_id),
            "recovery_code_position": recovery_code.position,
        },
    )
    db.commit()
    db.refresh(current_context.session)
    return AuthSessionRead.model_validate(current_context.session)
