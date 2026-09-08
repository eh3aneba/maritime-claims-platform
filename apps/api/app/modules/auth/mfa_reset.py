from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.mfa import get_totp_factor_for_user, revoke_totp_factor
from app.modules.auth.mfa_recovery_models import MfaRecoveryCode
from app.modules.auth.mfa_reset_models import MfaFactorResetRequest
from app.modules.auth.models import AuthSession, TotpMfaFactor
from app.modules.auth.service import revoke_auth_session
from app.modules.users.models import User

RESET_PENDING = "pending"
RESET_APPROVED = "approved"
RESET_REJECTED = "rejected"
RESET_CANCELLED = "cancelled"
RESET_EXECUTED = "executed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_reason(reason: str) -> str:
    normalized = " ".join(reason.strip().split())
    if len(normalized) < 5:
        raise ValueError("Reset reason is too short")
    if len(normalized) > 500:
        raise ValueError("Reset reason is too long")
    return normalized


def get_reset_request_for_tenant(
    db: Session,
    *,
    request_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
) -> MfaFactorResetRequest | None:
    stmt = select(MfaFactorResetRequest).where(
        MfaFactorResetRequest.id == request_id,
        MfaFactorResetRequest.organization_id == organization_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def list_reset_requests(
    db: Session,
    *,
    organization_id: UUID,
) -> list[MfaFactorResetRequest]:
    return list(
        db.scalars(
            select(MfaFactorResetRequest)
            .where(MfaFactorResetRequest.organization_id == organization_id)
            .order_by(
                MfaFactorResetRequest.created_at.desc(),
                MfaFactorResetRequest.id.desc(),
            )
        )
    )


def create_reset_request(
    db: Session,
    *,
    target_user: User,
    factor: TotpMfaFactor,
    requested_by: User,
    requested_auth_session: AuthSession,
    reason: str,
) -> MfaFactorResetRequest:
    if not target_user.is_active or target_user.deleted_at is not None:
        raise ValueError("Target user is inactive or unavailable")
    if target_user.organization_id != requested_by.organization_id:
        raise ValueError("MFA reset tenant mismatch")
    if (
        factor.organization_id != target_user.organization_id
        or factor.user_id != target_user.id
        or factor.revoked_at is not None
        or factor.confirmed_at is None
    ):
        raise ValueError("Active confirmed TOTP factor required")
    if (
        requested_auth_session.organization_id != requested_by.organization_id
        or requested_auth_session.user_id != requested_by.id
        or requested_auth_session.revoked_at is not None
    ):
        raise ValueError("Valid initiating authentication session required")

    existing = db.scalar(
        select(MfaFactorResetRequest)
        .where(
            MfaFactorResetRequest.factor_id == factor.id,
            MfaFactorResetRequest.status.in_([RESET_PENDING, RESET_APPROVED]),
        )
        .with_for_update()
    )
    if existing is not None:
        raise ValueError("An open reset request already exists for this factor")

    reset = MfaFactorResetRequest(
        organization_id=target_user.organization_id,
        user_id=target_user.id,
        factor_id=factor.id,
        requested_by_id=requested_by.id,
        requested_auth_session_id=requested_auth_session.id,
        reason=_clean_reason(reason),
        status=RESET_PENDING,
    )
    db.add(reset)
    db.flush()
    return reset


def approve_reset_request(
    *,
    reset: MfaFactorResetRequest,
    approved_by: User,
    approved_auth_session: AuthSession,
) -> MfaFactorResetRequest:
    if reset.status != RESET_PENDING:
        raise ValueError("Only a pending reset request can be approved")
    if approved_by.organization_id != reset.organization_id:
        raise ValueError("MFA reset tenant mismatch")
    if approved_by.id == reset.requested_by_id:
        raise PermissionError("The reset requester cannot approve the same request")
    if (
        approved_auth_session.organization_id != approved_by.organization_id
        or approved_auth_session.user_id != approved_by.id
        or approved_auth_session.revoked_at is not None
    ):
        raise ValueError("Valid approval authentication session required")

    reset.status = RESET_APPROVED
    reset.approved_at = _utc_now()
    reset.approved_by_id = approved_by.id
    reset.approved_auth_session_id = approved_auth_session.id
    return reset


def reject_reset_request(
    *,
    reset: MfaFactorResetRequest,
    rejected_by: User,
    rejected_auth_session: AuthSession,
    reason: str,
) -> MfaFactorResetRequest:
    if reset.status != RESET_PENDING:
        raise ValueError("Only a pending reset request can be rejected")
    if rejected_by.organization_id != reset.organization_id:
        raise ValueError("MFA reset tenant mismatch")
    if rejected_by.id == reset.requested_by_id:
        raise PermissionError("The reset requester cannot reject the same request")

    reset.status = RESET_REJECTED
    reset.rejected_at = _utc_now()
    reset.rejected_by_id = rejected_by.id
    reset.rejected_auth_session_id = rejected_auth_session.id
    reset.rejection_reason = _clean_reason(reason)
    return reset


def cancel_reset_request(
    *,
    reset: MfaFactorResetRequest,
    cancelled_by: User,
    cancelled_auth_session: AuthSession,
) -> MfaFactorResetRequest:
    if reset.status != RESET_PENDING:
        raise ValueError("Only a pending reset request can be cancelled")
    if cancelled_by.id != reset.requested_by_id:
        raise PermissionError("Only the reset requester can cancel the request")
    if cancelled_by.organization_id != reset.organization_id:
        raise ValueError("MFA reset tenant mismatch")

    reset.status = RESET_CANCELLED
    reset.cancelled_at = _utc_now()
    reset.cancelled_by_id = cancelled_by.id
    reset.cancelled_auth_session_id = cancelled_auth_session.id
    return reset


def execute_reset_request(
    db: Session,
    *,
    reset: MfaFactorResetRequest,
    executed_by: User,
    executed_auth_session: AuthSession,
) -> tuple[MfaFactorResetRequest, int, int]:
    if reset.status != RESET_APPROVED:
        raise ValueError("Only an approved reset request can be executed")
    if executed_by.organization_id != reset.organization_id:
        raise ValueError("MFA reset tenant mismatch")

    factor = get_totp_factor_for_user(
        db,
        factor_id=reset.factor_id,
        organization_id=reset.organization_id,
        user_id=reset.user_id,
    )
    if factor is None or factor.revoked_at is not None or factor.confirmed_at is None:
        raise ValueError("Target factor is no longer active and confirmed")

    now = _utc_now()
    recovery_codes = list(
        db.scalars(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.organization_id == reset.organization_id,
                MfaRecoveryCode.user_id == reset.user_id,
                MfaRecoveryCode.factor_id == reset.factor_id,
                MfaRecoveryCode.consumed_at.is_(None),
                MfaRecoveryCode.invalidated_at.is_(None),
            )
            .with_for_update()
        )
    )
    for recovery_code in recovery_codes:
        recovery_code.invalidated_at = now
        recovery_code.invalidated_by_session_id = executed_auth_session.id

    revoke_totp_factor(
        factor=factor,
        revoked_by_id=executed_by.id,
        reason=f"governed_factor_reset:{reset.id}",
    )

    sessions = list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.organization_id == reset.organization_id,
                AuthSession.user_id == reset.user_id,
                AuthSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    revoked_sessions = 0
    for auth_session in sessions:
        if revoke_auth_session(
            auth_session=auth_session,
            revoked_by_id=executed_by.id,
            reason=f"mfa_factor_reset:{reset.id}",
        ):
            revoked_sessions += 1

    reset.status = RESET_EXECUTED
    reset.executed_at = now
    reset.executed_by_id = executed_by.id
    reset.executed_auth_session_id = executed_auth_session.id
    db.flush()
    return reset, len(recovery_codes), revoked_sessions
