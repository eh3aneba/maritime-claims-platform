from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import verify_password
from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    ExternalIdentityBinding,
)
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User

settings = get_settings()

LOCAL_IDENTITY_SOURCE = "local"
PASSWORD_AUTH_METHOD = "password"
SUPPORTED_ENTERPRISE_IDENTITY_PROTOCOLS = {"oidc", "saml"}


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


def create_identity_provider(
    db: Session,
    *,
    organization_id: UUID,
    provider_key: str,
    display_name: str,
    protocol: str,
    issuer_identifier: str,
) -> EnterpriseIdentityProvider:
    normalized_protocol = protocol.strip().lower()
    if normalized_protocol not in SUPPORTED_ENTERPRISE_IDENTITY_PROTOCOLS:
        raise ValueError("Unsupported enterprise identity protocol")

    provider = EnterpriseIdentityProvider(
        organization_id=organization_id,
        provider_key=provider_key.strip().lower(),
        display_name=display_name.strip(),
        protocol=normalized_protocol,
        issuer_identifier=issuer_identifier.strip(),
        is_enabled=False,
    )
    db.add(provider)
    db.flush()
    return provider


def list_identity_providers(
    db: Session,
    *,
    organization_id: UUID,
) -> list[EnterpriseIdentityProvider]:
    return list(
        db.scalars(
            select(EnterpriseIdentityProvider)
            .where(EnterpriseIdentityProvider.organization_id == organization_id)
            .order_by(EnterpriseIdentityProvider.created_at, EnterpriseIdentityProvider.id)
        )
    )


def get_identity_provider_for_tenant(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> EnterpriseIdentityProvider | None:
    return db.scalar(
        select(EnterpriseIdentityProvider).where(
            EnterpriseIdentityProvider.id == provider_id,
            EnterpriseIdentityProvider.organization_id == organization_id,
        )
    )


def set_identity_provider_enabled(
    *,
    provider: EnterpriseIdentityProvider,
    enabled: bool,
) -> bool:
    if provider.is_enabled == enabled:
        return False
    provider.is_enabled = enabled
    return True


def _subject_fingerprint(provider_id: UUID, external_subject: str) -> str:
    normalized_subject = external_subject.strip()
    if not normalized_subject:
        raise ValueError("External subject is required")
    payload = f"{provider_id}\x00{normalized_subject}".encode("utf-8")
    return sha256(payload).hexdigest()


def get_user_for_tenant(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> User | None:
    return db.scalar(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization_id,
            User.deleted_at.is_(None),
        )
    )


def create_external_identity_binding(
    db: Session,
    *,
    provider: EnterpriseIdentityProvider,
    user: User,
    external_subject: str,
) -> ExternalIdentityBinding:
    if not provider.is_enabled:
        raise ValueError("Identity provider must be enabled before binding")
    if user.organization_id != provider.organization_id:
        raise ValueError("External identity binding tenant mismatch")

    existing_active = db.scalar(
        select(ExternalIdentityBinding).where(
            ExternalIdentityBinding.provider_id == provider.id,
            ExternalIdentityBinding.user_id == user.id,
            ExternalIdentityBinding.revoked_at.is_(None),
        )
    )
    if existing_active is not None:
        raise ValueError("User already has an active binding for this provider")

    fingerprint = _subject_fingerprint(provider.id, external_subject)
    existing_subject = db.scalar(
        select(ExternalIdentityBinding).where(
            ExternalIdentityBinding.provider_id == provider.id,
            ExternalIdentityBinding.subject_fingerprint == fingerprint,
        )
    )
    if existing_subject is not None:
        raise ValueError("External subject is already registered for this provider")

    binding = ExternalIdentityBinding(
        organization_id=provider.organization_id,
        provider_id=provider.id,
        user_id=user.id,
        subject_fingerprint=fingerprint,
    )
    db.add(binding)
    db.flush()
    return binding


def list_external_identity_bindings(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> list[ExternalIdentityBinding]:
    return list(
        db.scalars(
            select(ExternalIdentityBinding)
            .where(
                ExternalIdentityBinding.provider_id == provider_id,
                ExternalIdentityBinding.organization_id == organization_id,
            )
            .order_by(
                ExternalIdentityBinding.created_at,
                ExternalIdentityBinding.id,
            )
        )
    )


def get_external_identity_binding_for_tenant(
    db: Session,
    *,
    binding_id: UUID,
    organization_id: UUID,
) -> ExternalIdentityBinding | None:
    return db.scalar(
        select(ExternalIdentityBinding).where(
            ExternalIdentityBinding.id == binding_id,
            ExternalIdentityBinding.organization_id == organization_id,
        )
    )


def revoke_external_identity_binding(
    *,
    binding: ExternalIdentityBinding,
    revoked_by_id: UUID,
    reason: str = "admin_revocation",
) -> bool:
    if binding.revoked_at is not None:
        return False
    binding.revoked_at = _utc_now()
    binding.revoked_by_id = revoked_by_id
    binding.revocation_reason = reason
    return True
