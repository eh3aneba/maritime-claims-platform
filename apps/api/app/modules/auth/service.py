from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import verify_password
from app.modules.auth.models import AuthSession
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User

settings = get_settings()

LOCAL_IDENTITY_SOURCE = "local"
PASSWORD_AUTH_METHOD = "password"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def authenticate_user(
    db: Session,
    *,
    organization_slug: str,
    email: str,
    password: str,
) -> User | None:
    stmt = (
        select(User)
        .join(Organization, User.organization_id == Organization.id)
        .where(
            func.lower(Organization.slug) == organization_slug.strip().lower(),
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
            func.lower(User.email) == email.strip().lower(),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    user = db.scalar(stmt)
    if user is None or not verify_password(password, user.password_hash):
        return None

    user.last_login_at = _utc_now()
    return user


def create_auth_session(
    db: Session,
    *,
    user: User,
    identity_source: str = LOCAL_IDENTITY_SOURCE,
    auth_method: str = PASSWORD_AUTH_METHOD,
) -> AuthSession:
    now = _utc_now()
    session = AuthSession(
        organization_id=user.organization_id,
        user_id=user.id,
        identity_source=identity_source,
        auth_method=auth_method,
        expires_at=now + timedelta(minutes=settings.access_token_expire_minutes),
    )
    db.add(session)
    db.flush()
    return session


def get_valid_auth_session(
    db: Session,
    *,
    session_id: UUID,
    user_id: UUID,
    organization_id: UUID,
    identity_source: str,
    auth_method: str,
) -> AuthSession | None:
    auth_session = db.get(AuthSession, session_id)
    if auth_session is None:
        return None
    if auth_session.user_id != user_id or auth_session.organization_id != organization_id:
        return None
    if (
        auth_session.identity_source != identity_source
        or auth_session.auth_method != auth_method
    ):
        return None
    if auth_session.revoked_at is not None:
        return None
    if _as_utc(auth_session.expires_at) <= _utc_now():
        return None
    return auth_session


def get_auth_session_for_tenant(
    db: Session,
    *,
    session_id: UUID,
    organization_id: UUID,
) -> AuthSession | None:
    return db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.organization_id == organization_id,
        )
    )


def revoke_auth_session(
    *,
    auth_session: AuthSession,
    revoked_by_id: UUID,
    reason: str,
) -> bool:
    if auth_session.revoked_at is not None:
        return False
    auth_session.revoked_at = _utc_now()
    auth_session.revoked_by_id = revoked_by_id
    auth_session.revocation_reason = reason
    return True
