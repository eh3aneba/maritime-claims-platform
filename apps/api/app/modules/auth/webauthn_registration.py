import base64
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession
from app.modules.auth.webauthn_models import (
    WebAuthnRegistrationTransaction,
    WebAuthnRelyingPartyProfile,
)
from app.modules.auth.webauthn_profile import get_current_webauthn_rp_profile
from app.modules.users.models import User

WEBAUTHN_REGISTRATION_TTL_MINUTES = 5
WEBAUTHN_REGISTRATION_TIMEOUT_MS = 300_000


@dataclass(frozen=True)
class WebAuthnRegistrationMaterial:
    challenge: str
    user_handle: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _challenge_hash(challenge: str) -> str:
    return sha256(challenge.encode("ascii")).hexdigest()


def _validate_session_source(*, user: User, auth_session: AuthSession) -> None:
    if not user.is_active or user.deleted_at is not None:
        raise ValueError("WebAuthn registration user is inactive or unavailable")
    if (
        auth_session.organization_id != user.organization_id
        or auth_session.user_id != user.id
        or auth_session.revoked_at is not None
        or _as_utc(auth_session.expires_at) <= _utc_now()
    ):
        raise ValueError("WebAuthn registration requires a valid authentication session")


def _open_transaction_for_session(
    db: Session,
    *,
    auth_session_id: UUID,
) -> WebAuthnRegistrationTransaction | None:
    return db.scalar(
        select(WebAuthnRegistrationTransaction)
        .where(
            WebAuthnRegistrationTransaction.auth_session_id == auth_session_id,
            WebAuthnRegistrationTransaction.consumed_at.is_(None),
            WebAuthnRegistrationTransaction.cancelled_at.is_(None),
        )
        .with_for_update()
    )


def _validate_profile_snapshot(
    db: Session,
    *,
    transaction: WebAuthnRegistrationTransaction,
) -> WebAuthnRelyingPartyProfile:
    profile = db.get(WebAuthnRelyingPartyProfile, transaction.profile_id)
    if (
        profile is None
        or profile.organization_id != transaction.organization_id
        or profile.profile_number != transaction.profile_number
        or not hmac.compare_digest(profile.profile_hash, transaction.profile_hash)
    ):
        raise ValueError("WebAuthn registration profile source does not match")
    return profile


def begin_webauthn_registration(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
) -> tuple[
    WebAuthnRegistrationTransaction,
    WebAuthnRegistrationMaterial,
    WebAuthnRelyingPartyProfile,
    UUID | None,
]:
    _validate_session_source(user=user, auth_session=auth_session)
    profile = get_current_webauthn_rp_profile(
        db,
        organization_id=user.organization_id,
    )
    if profile is None:
        raise ValueError("WebAuthn relying-party profile is not configured")

    superseded_id: UUID | None = None
    existing = _open_transaction_for_session(db, auth_session_id=auth_session.id)
    if existing is not None:
        existing.cancelled_at = _utc_now()
        superseded_id = existing.id
        db.flush()

    challenge = _base64url(secrets.token_bytes(32))
    now = _utc_now()
    transaction = WebAuthnRegistrationTransaction(
        organization_id=user.organization_id,
        user_id=user.id,
        auth_session_id=auth_session.id,
        profile_id=profile.id,
        profile_number=profile.profile_number,
        profile_hash=profile.profile_hash,
        challenge_hash=_challenge_hash(challenge),
        expires_at=now + timedelta(minutes=WEBAUTHN_REGISTRATION_TTL_MINUTES),
    )
    db.add(transaction)
    db.flush()
    return (
        transaction,
        WebAuthnRegistrationMaterial(
            challenge=challenge,
            user_handle=_base64url(user.id.bytes),
        ),
        profile,
        superseded_id,
    )


def cancel_webauthn_registration(
    db: Session,
    *,
    transaction_id: UUID,
    user: User,
    auth_session: AuthSession,
) -> WebAuthnRegistrationTransaction:
    _validate_session_source(user=user, auth_session=auth_session)
    transaction = db.scalar(
        select(WebAuthnRegistrationTransaction)
        .where(WebAuthnRegistrationTransaction.id == transaction_id)
        .with_for_update()
    )
    if transaction is None:
        raise ValueError("WebAuthn registration transaction not found")
    if (
        transaction.organization_id != user.organization_id
        or transaction.user_id != user.id
        or transaction.auth_session_id != auth_session.id
    ):
        raise ValueError("WebAuthn registration transaction not found")
    _validate_profile_snapshot(db, transaction=transaction)
    if transaction.consumed_at is not None:
        raise ValueError("WebAuthn registration transaction is already consumed")
    if transaction.cancelled_at is not None:
        raise ValueError("WebAuthn registration transaction is already cancelled")

    transaction.cancelled_at = _utc_now()
    db.flush()
    return transaction
