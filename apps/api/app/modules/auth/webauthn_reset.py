from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.auth.mfa import get_current_totp_factor
from app.modules.auth.models import AuthSession
from app.modules.auth.service import revoke_auth_session
from app.modules.auth.webauthn_models import (
    WebAuthnAuthenticationTransaction,
    WebAuthnCredential,
    WebAuthnRegistrationTransaction,
)
from app.modules.auth.webauthn_registration import _as_utc
from app.modules.auth.webauthn_reset_models import WebAuthnCredentialResetRequest
from app.modules.users.models import User

RESET_PENDING = "pending"
RESET_APPROVED = "approved"
RESET_REJECTED = "rejected"
RESET_CANCELLED = "cancelled"
RESET_EXECUTED = "executed"
WEBAUTHN_REENROLLMENT_TTL_MINUTES = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_reason(reason: str) -> str:
    normalized = " ".join(reason.strip().split())
    if len(normalized) < 5:
        raise ValueError("Reset reason is too short")
    if len(normalized) > 500:
        raise ValueError("Reset reason is too long")
    return normalized


def _validate_actor_session(*, user: User, auth_session: AuthSession) -> None:
    if not user.is_active or user.deleted_at is not None:
        raise ValueError("Reset actor is inactive or unavailable")
    if (
        auth_session.organization_id != user.organization_id
        or auth_session.user_id != user.id
        or auth_session.revoked_at is not None
    ):
        raise ValueError("Valid authentication session required")


def get_webauthn_reset_for_tenant(
    db: Session,
    *,
    request_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
) -> WebAuthnCredentialResetRequest | None:
    stmt = select(WebAuthnCredentialResetRequest).where(
        WebAuthnCredentialResetRequest.id == request_id,
        WebAuthnCredentialResetRequest.organization_id == organization_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def list_webauthn_resets(
    db: Session,
    *,
    organization_id: UUID,
) -> list[WebAuthnCredentialResetRequest]:
    return list(
        db.scalars(
            select(WebAuthnCredentialResetRequest)
            .where(WebAuthnCredentialResetRequest.organization_id == organization_id)
            .order_by(
                WebAuthnCredentialResetRequest.created_at.desc(),
                WebAuthnCredentialResetRequest.id.desc(),
            )
        )
    )


def get_active_webauthn_credential_for_user(
    db: Session,
    *,
    credential_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> WebAuthnCredential | None:
    stmt = select(WebAuthnCredential).where(
        WebAuthnCredential.id == credential_id,
        WebAuthnCredential.organization_id == organization_id,
        WebAuthnCredential.user_id == user_id,
        WebAuthnCredential.revoked_at.is_(None),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def create_webauthn_reset_request(
    db: Session,
    *,
    target_user: User,
    credential: WebAuthnCredential,
    requested_by: User,
    requested_auth_session: AuthSession,
    reason: str,
) -> WebAuthnCredentialResetRequest:
    _validate_actor_session(user=requested_by, auth_session=requested_auth_session)
    if not target_user.is_active or target_user.deleted_at is not None:
        raise ValueError("Target user is inactive or unavailable")
    if target_user.organization_id != requested_by.organization_id:
        raise ValueError("WebAuthn reset tenant mismatch")
    if (
        credential.organization_id != target_user.organization_id
        or credential.user_id != target_user.id
        or credential.revoked_at is not None
    ):
        raise ValueError("Active WebAuthn credential required")

    existing = db.scalar(
        select(WebAuthnCredentialResetRequest)
        .where(
            WebAuthnCredentialResetRequest.credential_id == credential.id,
            WebAuthnCredentialResetRequest.status.in_([RESET_PENDING, RESET_APPROVED]),
        )
        .with_for_update()
    )
    if existing is not None:
        raise ValueError("An open WebAuthn reset request already exists for this credential")

    reset = WebAuthnCredentialResetRequest(
        organization_id=target_user.organization_id,
        user_id=target_user.id,
        credential_id=credential.id,
        requested_by_id=requested_by.id,
        requested_auth_session_id=requested_auth_session.id,
        reason=_clean_reason(reason),
        status=RESET_PENDING,
    )
    db.add(reset)
    db.flush()
    return reset


def approve_webauthn_reset_request(
    *,
    reset: WebAuthnCredentialResetRequest,
    approved_by: User,
    approved_auth_session: AuthSession,
) -> WebAuthnCredentialResetRequest:
    _validate_actor_session(user=approved_by, auth_session=approved_auth_session)
    if reset.status != RESET_PENDING:
        raise ValueError("Only a pending WebAuthn reset request can be approved")
    if approved_by.organization_id != reset.organization_id:
        raise ValueError("WebAuthn reset tenant mismatch")
    if approved_by.id == reset.requested_by_id:
        raise PermissionError("The reset requester cannot approve the same request")

    reset.status = RESET_APPROVED
    reset.approved_at = _utc_now()
    reset.approved_by_id = approved_by.id
    reset.approved_auth_session_id = approved_auth_session.id
    return reset


def reject_webauthn_reset_request(
    *,
    reset: WebAuthnCredentialResetRequest,
    rejected_by: User,
    rejected_auth_session: AuthSession,
    reason: str,
) -> WebAuthnCredentialResetRequest:
    _validate_actor_session(user=rejected_by, auth_session=rejected_auth_session)
    if reset.status != RESET_PENDING:
        raise ValueError("Only a pending WebAuthn reset request can be rejected")
    if rejected_by.organization_id != reset.organization_id:
        raise ValueError("WebAuthn reset tenant mismatch")
    if rejected_by.id == reset.requested_by_id:
        raise PermissionError("The reset requester cannot reject the same request")

    reset.status = RESET_REJECTED
    reset.rejected_at = _utc_now()
    reset.rejected_by_id = rejected_by.id
    reset.rejected_auth_session_id = rejected_auth_session.id
    reset.rejection_reason = _clean_reason(reason)
    return reset


def cancel_webauthn_reset_request(
    *,
    reset: WebAuthnCredentialResetRequest,
    cancelled_by: User,
    cancelled_auth_session: AuthSession,
) -> WebAuthnCredentialResetRequest:
    _validate_actor_session(user=cancelled_by, auth_session=cancelled_auth_session)
    if reset.status != RESET_PENDING:
        raise ValueError("Only a pending WebAuthn reset request can be cancelled")
    if cancelled_by.organization_id != reset.organization_id:
        raise ValueError("WebAuthn reset tenant mismatch")
    if cancelled_by.id != reset.requested_by_id:
        raise PermissionError("Only the reset requester can cancel the request")

    reset.status = RESET_CANCELLED
    reset.cancelled_at = _utc_now()
    reset.cancelled_by_id = cancelled_by.id
    reset.cancelled_auth_session_id = cancelled_auth_session.id
    return reset


def _cancel_open_webauthn_transactions(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    now: datetime,
) -> tuple[int, int]:
    registrations = list(
        db.scalars(
            select(WebAuthnRegistrationTransaction)
            .where(
                WebAuthnRegistrationTransaction.organization_id == organization_id,
                WebAuthnRegistrationTransaction.user_id == user_id,
                WebAuthnRegistrationTransaction.consumed_at.is_(None),
                WebAuthnRegistrationTransaction.cancelled_at.is_(None),
            )
            .with_for_update()
        )
    )
    for transaction in registrations:
        transaction.cancelled_at = now

    authentications = list(
        db.scalars(
            select(WebAuthnAuthenticationTransaction)
            .where(
                WebAuthnAuthenticationTransaction.organization_id == organization_id,
                WebAuthnAuthenticationTransaction.user_id == user_id,
                WebAuthnAuthenticationTransaction.consumed_at.is_(None),
                WebAuthnAuthenticationTransaction.cancelled_at.is_(None),
            )
            .with_for_update()
        )
    )
    for transaction in authentications:
        transaction.cancelled_at = now
    return len(registrations), len(authentications)


def _revoke_target_sessions(
    db: Session,
    *,
    reset: WebAuthnCredentialResetRequest,
    executed_by: User,
) -> int:
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
    revoked = 0
    for auth_session in sessions:
        if revoke_auth_session(
            auth_session=auth_session,
            revoked_by_id=executed_by.id,
            reason=f"webauthn_credential_reset:{reset.id}",
        ):
            revoked += 1
    return revoked


def _has_active_mfa_factor(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> bool:
    factor = get_current_totp_factor(
        db,
        organization_id=organization_id,
        user_id=user_id,
    )
    if factor is not None and factor.confirmed_at is not None and factor.revoked_at is None:
        return True
    return (
        db.scalar(
            select(WebAuthnCredential.id)
            .where(
                WebAuthnCredential.organization_id == organization_id,
                WebAuthnCredential.user_id == user_id,
                WebAuthnCredential.revoked_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def execute_webauthn_reset_request(
    db: Session,
    *,
    reset: WebAuthnCredentialResetRequest,
    executed_by: User,
    executed_auth_session: AuthSession,
) -> tuple[WebAuthnCredentialResetRequest, int, int, int, bool]:
    _validate_actor_session(user=executed_by, auth_session=executed_auth_session)
    if reset.status != RESET_APPROVED:
        raise ValueError("Only an approved WebAuthn reset request can be executed")
    if executed_by.organization_id != reset.organization_id:
        raise ValueError("WebAuthn reset tenant mismatch")

    credential = get_active_webauthn_credential_for_user(
        db,
        credential_id=reset.credential_id,
        organization_id=reset.organization_id,
        user_id=reset.user_id,
        for_update=True,
    )
    if credential is None:
        raise ValueError("Target WebAuthn credential is no longer active")

    now = _utc_now()
    credential.revoked_at = now
    cancelled_registrations, cancelled_authentications = _cancel_open_webauthn_transactions(
        db,
        organization_id=reset.organization_id,
        user_id=reset.user_id,
        now=now,
    )
    revoked_sessions = _revoke_target_sessions(db, reset=reset, executed_by=executed_by)

    reset.status = RESET_EXECUTED
    reset.executed_at = now
    reset.executed_by_id = executed_by.id
    reset.executed_auth_session_id = executed_auth_session.id

    reenrollment_authorized = not _has_active_mfa_factor(
        db,
        organization_id=reset.organization_id,
        user_id=reset.user_id,
    )
    if reenrollment_authorized:
        stale_grants = list(
            db.scalars(
                select(WebAuthnCredentialResetRequest)
                .where(
                    WebAuthnCredentialResetRequest.organization_id == reset.organization_id,
                    WebAuthnCredentialResetRequest.user_id == reset.user_id,
                    WebAuthnCredentialResetRequest.id != reset.id,
                    WebAuthnCredentialResetRequest.status == RESET_EXECUTED,
                    WebAuthnCredentialResetRequest.reenrollment_consumed_at.is_(None),
                    WebAuthnCredentialResetRequest.reenrollment_expires_at.is_not(None),
                    WebAuthnCredentialResetRequest.reenrollment_expires_at > now,
                )
                .with_for_update()
            )
        )
        for stale in stale_grants:
            stale.reenrollment_expires_at = now
        reset.reenrollment_expires_at = now + timedelta(minutes=WEBAUTHN_REENROLLMENT_TTL_MINUTES)

    db.flush()
    return (
        reset,
        cancelled_registrations,
        cancelled_authentications,
        revoked_sessions,
        reenrollment_authorized,
    )


def claim_webauthn_reenrollment_grant(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
) -> WebAuthnCredentialResetRequest | None:
    _validate_actor_session(user=user, auth_session=auth_session)
    if _has_active_mfa_factor(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
    ):
        return None

    now = _utc_now()
    reset = db.scalar(
        select(WebAuthnCredentialResetRequest)
        .where(
            WebAuthnCredentialResetRequest.organization_id == user.organization_id,
            WebAuthnCredentialResetRequest.user_id == user.id,
            WebAuthnCredentialResetRequest.status == RESET_EXECUTED,
            WebAuthnCredentialResetRequest.reenrollment_expires_at.is_not(None),
            WebAuthnCredentialResetRequest.reenrollment_expires_at > now,
            WebAuthnCredentialResetRequest.reenrollment_consumed_at.is_(None),
            or_(
                WebAuthnCredentialResetRequest.reenrollment_auth_session_id.is_(None),
                WebAuthnCredentialResetRequest.reenrollment_auth_session_id == auth_session.id,
            ),
        )
        .order_by(WebAuthnCredentialResetRequest.executed_at.desc())
        .with_for_update()
    )
    if reset is None:
        return None
    if reset.reenrollment_auth_session_id is None:
        reset.reenrollment_auth_session_id = auth_session.id
        reset.reenrollment_claimed_at = now
        db.flush()
    return reset


def get_reenrollment_grant_for_registration(
    db: Session,
    *,
    transaction_id: UUID,
    user: User,
    auth_session: AuthSession,
) -> WebAuthnCredentialResetRequest | None:
    transaction = db.get(WebAuthnRegistrationTransaction, transaction_id)
    if transaction is None:
        return None
    reset_id = transaction.reenrollment_reset_request_id
    if reset_id is None:
        return None
    if (
        transaction.organization_id != user.organization_id
        or transaction.user_id != user.id
        or transaction.auth_session_id != auth_session.id
    ):
        raise ValueError("WebAuthn re-enrollment transaction is not bound to this session")

    reset = db.scalar(
        select(WebAuthnCredentialResetRequest)
        .where(WebAuthnCredentialResetRequest.id == reset_id)
        .with_for_update()
    )
    now = _utc_now()
    if reset is None or (
        reset.organization_id != user.organization_id
        or reset.user_id != user.id
        or reset.status != RESET_EXECUTED
        or reset.reenrollment_auth_session_id != auth_session.id
        or reset.reenrollment_consumed_at is not None
        or reset.reenrollment_expires_at is None
        or _as_utc(reset.reenrollment_expires_at) <= now
    ):
        raise ValueError("WebAuthn re-enrollment authorization is invalid or expired")
    if _has_active_mfa_factor(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
    ):
        raise ValueError("WebAuthn re-enrollment authorization is no longer applicable")
    return reset


def consume_webauthn_reenrollment_grant(
    *,
    reset: WebAuthnCredentialResetRequest,
    credential: WebAuthnCredential,
) -> None:
    if reset.reenrollment_consumed_at is not None:
        raise ValueError("WebAuthn re-enrollment authorization is already consumed")
    if (
        credential.organization_id != reset.organization_id
        or credential.user_id != reset.user_id
    ):
        raise ValueError("Replacement WebAuthn credential does not match reset subject")
    reset.reenrollment_consumed_at = _utc_now()
    reset.reenrollment_credential_id = credential.id
