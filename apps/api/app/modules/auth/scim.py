import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import AuthSession
from app.modules.auth.scim_models import (
    ScimProvisioningProfile,
    ScimProvisioningToken,
    ScimUserBinding,
    ScimUserProvisioningGrant,
)
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User, UserRole

SCIM_SERVICE_BASE_PATH = "/api/v1/scim/v2"
MIN_SCIM_TOKEN_TTL_DAYS = 1
MAX_SCIM_TOKEN_TTL_DAYS = 90
SCIM_TOKEN_PREFIX = "mcri_scim_"
SCIM_TOKEN_RANDOM_BYTES = 48
MIN_SCIM_GRANT_TTL_HOURS = 1
MAX_SCIM_GRANT_TTL_HOURS = 168
MAX_SCIM_EXTERNAL_ID_LENGTH = 512
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"

settings = get_settings()


@dataclass(frozen=True)
class IssuedScimToken:
    token_record: ScimProvisioningToken
    plaintext_token: str


@dataclass(frozen=True)
class ScimServiceContext:
    organization_id: UUID
    profile: ScimProvisioningProfile
    token: ScimProvisioningToken


@dataclass(frozen=True)
class ScimManagedUser:
    user: User
    binding: ScimUserBinding


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _profile_hash(
    *,
    organization_id: UUID,
    client_name: str,
    token_ttl_days: int,
    enabled: bool,
    user_provisioning_enabled: bool,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "client_name": client_name,
        "service_base_path": SCIM_SERVICE_BASE_PATH,
        "token_ttl_days": token_ttl_days,
        "enabled": enabled,
        "user_provisioning_enabled": user_provisioning_enabled,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _token_digest(plaintext_token: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        plaintext_token.encode("utf-8"),
        sha256,
    ).hexdigest()


def normalize_scim_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 320 or "@" not in normalized:
        raise ValueError("A valid SCIM userName email is required")
    return normalized


def scim_value_fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def scim_email_fingerprint(value: str) -> str:
    return scim_value_fingerprint(normalize_scim_email(value))


def _external_id_fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_SCIM_EXTERNAL_ID_LENGTH:
        raise ValueError("SCIM externalId is too long")
    return scim_value_fingerprint(normalized)


def _grant_hash(
    *,
    organization_id: UUID,
    profile: ScimProvisioningProfile,
    email_fingerprint: str,
    role: UserRole,
    expires_at: datetime,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "profile_id": str(profile.id),
        "profile_number": profile.profile_number,
        "profile_hash": profile.profile_hash,
        "email_fingerprint": email_fingerprint,
        "role": role.value,
        "expires_at": expires_at.isoformat(),
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def list_scim_provisioning_profiles(
    db: Session,
    *,
    organization_id: UUID,
) -> list[ScimProvisioningProfile]:
    return list(
        db.scalars(
            select(ScimProvisioningProfile)
            .where(ScimProvisioningProfile.organization_id == organization_id)
            .order_by(ScimProvisioningProfile.profile_number, ScimProvisioningProfile.id)
        )
    )


def get_current_scim_provisioning_profile(
    db: Session,
    *,
    organization_id: UUID,
) -> ScimProvisioningProfile | None:
    return db.scalar(
        select(ScimProvisioningProfile)
        .where(ScimProvisioningProfile.organization_id == organization_id)
        .order_by(
            ScimProvisioningProfile.profile_number.desc(),
            ScimProvisioningProfile.id.desc(),
        )
        .limit(1)
    )


def create_scim_provisioning_profile(
    db: Session,
    *,
    organization_id: UUID,
    client_name: str,
    token_ttl_days: int,
    enabled: bool,
    created_by_id: UUID,
    user_provisioning_enabled: bool = False,
) -> ScimProvisioningProfile:
    normalized_name = client_name.strip()
    if not normalized_name:
        raise ValueError("SCIM provisioning client name is required")
    if len(normalized_name) > 160:
        raise ValueError("SCIM provisioning client name is too long")
    if not MIN_SCIM_TOKEN_TTL_DAYS <= token_ttl_days <= MAX_SCIM_TOKEN_TTL_DAYS:
        raise ValueError(
            f"SCIM token lifetime must be between {MIN_SCIM_TOKEN_TTL_DAYS} and {MAX_SCIM_TOKEN_TTL_DAYS} days"
        )

    organization = db.scalar(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    )
    if (
        organization is None
        or organization.deleted_at is not None
        or organization.status != OrganizationStatus.ACTIVE
    ):
        raise ValueError("Organization is inactive or unavailable")

    digest = _profile_hash(
        organization_id=organization_id,
        client_name=normalized_name,
        token_ttl_days=token_ttl_days,
        enabled=enabled,
        user_provisioning_enabled=user_provisioning_enabled,
    )
    existing = db.scalar(
        select(ScimProvisioningProfile).where(
            ScimProvisioningProfile.organization_id == organization_id,
            ScimProvisioningProfile.profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    current = get_current_scim_provisioning_profile(
        db,
        organization_id=organization_id,
    )
    profile = ScimProvisioningProfile(
        organization_id=organization_id,
        profile_number=1 if current is None else current.profile_number + 1,
        client_name=normalized_name,
        service_base_path=SCIM_SERVICE_BASE_PATH,
        token_ttl_days=token_ttl_days,
        enabled=enabled,
        user_provisioning_enabled=user_provisioning_enabled,
        profile_hash=digest,
        previous_profile_hash=None if current is None else current.profile_hash,
        created_by_id=created_by_id,
    )
    db.add(profile)
    db.flush()
    return profile


def issue_scim_provisioning_token(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    created_by_id: UUID,
) -> IssuedScimToken:
    profile = db.scalar(
        select(ScimProvisioningProfile)
        .where(
            ScimProvisioningProfile.id == profile_id,
            ScimProvisioningProfile.organization_id == organization_id,
        )
        .with_for_update()
    )
    if profile is None:
        raise ValueError("SCIM provisioning profile not found")

    current = get_current_scim_provisioning_profile(db, organization_id=organization_id)
    if (
        current is None
        or current.id != profile.id
        or current.profile_number != profile.profile_number
        or not hmac.compare_digest(current.profile_hash, profile.profile_hash)
    ):
        raise ValueError("SCIM token can only be issued for the exact current provisioning profile")
    if not profile.enabled:
        raise ValueError("SCIM provisioning profile must be enabled before token issuance")

    now = _utc_now()
    previous_tokens = list(
        db.scalars(
            select(ScimProvisioningToken)
            .where(
                ScimProvisioningToken.organization_id == organization_id,
                ScimProvisioningToken.profile_id == profile.id,
                ScimProvisioningToken.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    for old_token in previous_tokens:
        old_token.revoked_at = now
        old_token.revoked_by_id = created_by_id
        old_token.revocation_reason = "rotated"
    if previous_tokens:
        db.flush()

    plaintext = SCIM_TOKEN_PREFIX + secrets.token_urlsafe(SCIM_TOKEN_RANDOM_BYTES)
    digest = _token_digest(plaintext)
    record = ScimProvisioningToken(
        organization_id=organization_id,
        profile_id=profile.id,
        profile_number=profile.profile_number,
        profile_hash=profile.profile_hash,
        token_digest=digest,
        token_prefix=plaintext[:16],
        expires_at=now + timedelta(days=profile.token_ttl_days),
        created_by_id=created_by_id,
    )
    db.add(record)
    db.flush()
    return IssuedScimToken(token_record=record, plaintext_token=plaintext)


def get_scim_token_for_tenant(
    db: Session,
    *,
    organization_id: UUID,
    token_id: UUID,
) -> ScimProvisioningToken | None:
    return db.scalar(
        select(ScimProvisioningToken).where(
            ScimProvisioningToken.id == token_id,
            ScimProvisioningToken.organization_id == organization_id,
        )
    )


def revoke_scim_provisioning_token(
    *,
    token: ScimProvisioningToken,
    revoked_by_id: UUID,
    reason: str = "admin_revocation",
) -> bool:
    if token.revoked_at is not None:
        return False
    token.revoked_at = _utc_now()
    token.revoked_by_id = revoked_by_id
    token.revocation_reason = reason
    return True


def authenticate_scim_bearer_token(
    db: Session,
    *,
    plaintext_token: str,
) -> ScimServiceContext | None:
    if not plaintext_token.startswith(SCIM_TOKEN_PREFIX):
        return None
    digest = _token_digest(plaintext_token)
    token = db.scalar(
        select(ScimProvisioningToken).where(
            ScimProvisioningToken.token_digest == digest,
        )
    )
    if token is None or token.revoked_at is not None:
        return None

    now = _utc_now()
    if _as_aware(token.expires_at) <= now:
        return None

    profile = db.get(ScimProvisioningProfile, token.profile_id)
    if (
        profile is None
        or profile.organization_id != token.organization_id
        or profile.profile_number != token.profile_number
        or not hmac.compare_digest(profile.profile_hash, token.profile_hash)
        or not profile.enabled
    ):
        return None

    current = get_current_scim_provisioning_profile(
        db,
        organization_id=token.organization_id,
    )
    if (
        current is None
        or current.id != profile.id
        or current.profile_number != profile.profile_number
        or not hmac.compare_digest(current.profile_hash, profile.profile_hash)
    ):
        return None

    organization = db.get(Organization, token.organization_id)
    if (
        organization is None
        or organization.deleted_at is not None
        or organization.status != OrganizationStatus.ACTIVE
    ):
        return None

    return ScimServiceContext(
        organization_id=token.organization_id,
        profile=profile,
        token=token,
    )


def scim_user_provisioning_is_enabled(context: ScimServiceContext) -> bool:
    return bool(context.profile.user_provisioning_enabled)


def create_scim_user_provisioning_grant(
    db: Session,
    *,
    organization_id: UUID,
    email: str,
    role: UserRole,
    ttl_hours: int,
    created_by_id: UUID,
) -> ScimUserProvisioningGrant:
    if role == UserRole.ADMIN:
        raise ValueError("SCIM provisioning grants cannot create Admin users")
    if role not in {UserRole.CLAIMS_HANDLER, UserRole.CLAIMS_MANAGER}:
        raise ValueError("Unsupported SCIM provisioning grant role")
    if not MIN_SCIM_GRANT_TTL_HOURS <= ttl_hours <= MAX_SCIM_GRANT_TTL_HOURS:
        raise ValueError(
            f"SCIM User grant lifetime must be between {MIN_SCIM_GRANT_TTL_HOURS} and {MAX_SCIM_GRANT_TTL_HOURS} hours"
        )

    normalized_email = normalize_scim_email(email)
    email_fingerprint = scim_value_fingerprint(normalized_email)
    current = get_current_scim_provisioning_profile(db, organization_id=organization_id)
    if (
        current is None
        or not current.enabled
        or not current.user_provisioning_enabled
    ):
        raise ValueError("Current SCIM profile is not enabled for User provisioning")

    existing_user = db.scalar(
        select(User).where(
            User.organization_id == organization_id,
            func.lower(User.email) == normalized_email,
        )
    )
    if existing_user is not None:
        raise ValueError("A local User with this email already exists and cannot be claimed by SCIM")

    now = _utc_now()
    previous_grants = list(
        db.scalars(
            select(ScimUserProvisioningGrant)
            .where(
                ScimUserProvisioningGrant.organization_id == organization_id,
                ScimUserProvisioningGrant.email_fingerprint == email_fingerprint,
                ScimUserProvisioningGrant.consumed_at.is_(None),
                ScimUserProvisioningGrant.cancelled_at.is_(None),
            )
            .with_for_update()
        )
    )
    for previous in previous_grants:
        previous.cancelled_at = now
        previous.cancelled_by_id = created_by_id
        previous.cancellation_reason = "superseded"
    if previous_grants:
        db.flush()

    expires_at = now + timedelta(hours=ttl_hours)
    grant = ScimUserProvisioningGrant(
        organization_id=organization_id,
        profile_id=current.id,
        profile_number=current.profile_number,
        profile_hash=current.profile_hash,
        email_fingerprint=email_fingerprint,
        role=role.value,
        grant_hash=_grant_hash(
            organization_id=organization_id,
            profile=current,
            email_fingerprint=email_fingerprint,
            role=role,
            expires_at=expires_at,
        ),
        expires_at=expires_at,
        created_by_id=created_by_id,
    )
    db.add(grant)
    db.flush()
    return grant


def list_scim_user_provisioning_grants(
    db: Session,
    *,
    organization_id: UUID,
) -> list[ScimUserProvisioningGrant]:
    return list(
        db.scalars(
            select(ScimUserProvisioningGrant)
            .where(ScimUserProvisioningGrant.organization_id == organization_id)
            .order_by(ScimUserProvisioningGrant.created_at.desc(), ScimUserProvisioningGrant.id.desc())
        )
    )


def get_scim_user_provisioning_grant(
    db: Session,
    *,
    organization_id: UUID,
    grant_id: UUID,
) -> ScimUserProvisioningGrant | None:
    return db.scalar(
        select(ScimUserProvisioningGrant).where(
            ScimUserProvisioningGrant.id == grant_id,
            ScimUserProvisioningGrant.organization_id == organization_id,
        )
    )


def cancel_scim_user_provisioning_grant(
    grant: ScimUserProvisioningGrant,
    *,
    cancelled_by_id: UUID,
    reason: str = "admin_cancellation",
) -> bool:
    if grant.consumed_at is not None or grant.cancelled_at is not None:
        return False
    grant.cancelled_at = _utc_now()
    grant.cancelled_by_id = cancelled_by_id
    grant.cancellation_reason = reason
    return True


def _resolve_display_name(display_name: str | None, name: dict[str, object] | None) -> str:
    candidate = (display_name or "").strip()
    if not candidate and name is not None:
        formatted = name.get("formatted")
        if isinstance(formatted, str):
            candidate = formatted.strip()
    if not candidate:
        raise ValueError("SCIM displayName or name.formatted is required")
    if len(candidate) > 200:
        raise ValueError("SCIM display name is too long")
    return candidate


def _reject_external_authority_fields(*, roles_present: bool, groups_present: bool) -> None:
    if roles_present or groups_present:
        raise ValueError("SCIM roles/groups are not accepted as application authority")


def provision_scim_user(
    db: Session,
    *,
    context: ScimServiceContext,
    user_name: str,
    display_name: str | None,
    name: dict[str, object] | None,
    active: bool,
    external_id: str | None,
    roles_present: bool,
    groups_present: bool,
) -> ScimManagedUser:
    if not scim_user_provisioning_is_enabled(context):
        raise PermissionError("SCIM User provisioning capability is disabled")
    _reject_external_authority_fields(
        roles_present=roles_present,
        groups_present=groups_present,
    )

    normalized_email = normalize_scim_email(user_name)
    email_fingerprint = scim_value_fingerprint(normalized_email)
    resolved_name = _resolve_display_name(display_name, name)
    external_fingerprint = _external_id_fingerprint(external_id)
    now = _utc_now()

    grant = db.scalar(
        select(ScimUserProvisioningGrant)
        .where(
            ScimUserProvisioningGrant.organization_id == context.organization_id,
            ScimUserProvisioningGrant.profile_id == context.profile.id,
            ScimUserProvisioningGrant.profile_number == context.profile.profile_number,
            ScimUserProvisioningGrant.profile_hash == context.profile.profile_hash,
            ScimUserProvisioningGrant.email_fingerprint == email_fingerprint,
            ScimUserProvisioningGrant.consumed_at.is_(None),
            ScimUserProvisioningGrant.cancelled_at.is_(None),
        )
        .order_by(ScimUserProvisioningGrant.created_at.desc())
        .with_for_update()
    )
    if grant is None or _as_aware(grant.expires_at) <= now:
        raise PermissionError("No valid local SCIM User provisioning grant matches this userName")

    existing_user = db.scalar(
        select(User).where(
            User.organization_id == context.organization_id,
            func.lower(User.email) == normalized_email,
        )
    )
    if existing_user is not None:
        raise ValueError("A local User with this email already exists and cannot be claimed by SCIM")

    role = UserRole(grant.role)
    if role == UserRole.ADMIN:
        raise ValueError("SCIM cannot create Admin users")

    user = User(
        organization_id=context.organization_id,
        email=normalized_email,
        full_name=resolved_name,
        password_hash=hash_password(secrets.token_urlsafe(64)),
        role=role,
        is_active=active,
    )
    db.add(user)
    db.flush()

    binding = ScimUserBinding(
        organization_id=context.organization_id,
        user_id=user.id,
        grant_id=grant.id,
        created_profile_id=context.profile.id,
        created_profile_number=context.profile.profile_number,
        created_profile_hash=context.profile.profile_hash,
        user_name_fingerprint=email_fingerprint,
        external_id_fingerprint=external_fingerprint,
        last_synced_at=now,
        deactivated_at=None if active else now,
    )
    db.add(binding)
    grant.consumed_at = now
    grant.consumed_user_id = user.id
    db.flush()
    return ScimManagedUser(user=user, binding=binding)


def _managed_user_query(*, organization_id: UUID):
    return (
        select(User, ScimUserBinding)
        .join(ScimUserBinding, ScimUserBinding.user_id == User.id)
        .where(
            User.organization_id == organization_id,
            ScimUserBinding.organization_id == organization_id,
        )
    )


def get_scim_managed_user(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    lock: bool = False,
) -> ScimManagedUser | None:
    statement = _managed_user_query(organization_id=organization_id).where(User.id == user_id)
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).first()
    if row is None:
        return None
    return ScimManagedUser(user=row[0], binding=row[1])


def list_scim_managed_users(
    db: Session,
    *,
    organization_id: UUID,
    user_name: str | None = None,
    limit: int = 100,
) -> list[ScimManagedUser]:
    statement = _managed_user_query(organization_id=organization_id)
    if user_name is not None:
        normalized = normalize_scim_email(user_name)
        statement = statement.where(func.lower(User.email) == normalized)
    rows = db.execute(statement.order_by(User.email, User.id).limit(max(1, min(limit, 100)))).all()
    return [ScimManagedUser(user=row[0], binding=row[1]) for row in rows]


def _revoke_active_user_sessions(db: Session, *, user: User, now: datetime) -> int:
    sessions = list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.organization_id == user.organization_id,
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    for session in sessions:
        session.revoked_at = now
        session.revocation_reason = "scim_deprovisioned"
    return len(sessions)


def replace_scim_managed_user(
    db: Session,
    *,
    context: ScimServiceContext,
    user_id: UUID,
    user_name: str,
    display_name: str | None,
    name: dict[str, object] | None,
    active: bool,
    external_id: str | None,
    external_id_present: bool,
    roles_present: bool,
    groups_present: bool,
) -> tuple[ScimManagedUser, int]:
    if not scim_user_provisioning_is_enabled(context):
        raise PermissionError("SCIM User provisioning capability is disabled")
    _reject_external_authority_fields(
        roles_present=roles_present,
        groups_present=groups_present,
    )

    managed = get_scim_managed_user(
        db,
        organization_id=context.organization_id,
        user_id=user_id,
        lock=True,
    )
    if managed is None:
        raise LookupError("SCIM managed User not found")

    normalized_email = normalize_scim_email(user_name)
    if normalized_email != managed.user.email.lower():
        raise ValueError("SCIM userName cannot change an application's User email")
    if not hmac.compare_digest(
        scim_value_fingerprint(normalized_email),
        managed.binding.user_name_fingerprint,
    ):
        raise ValueError("SCIM userName lineage mismatch")

    if external_id_present:
        proposed_external = _external_id_fingerprint(external_id)
        stored_external = managed.binding.external_id_fingerprint
        if stored_external is None and proposed_external is not None:
            raise ValueError("SCIM externalId cannot be added after User creation")
        if stored_external is not None and proposed_external is None:
            raise ValueError("SCIM externalId cannot be removed after User creation")
        if (
            stored_external is not None
            and proposed_external is not None
            and not hmac.compare_digest(stored_external, proposed_external)
        ):
            raise ValueError("SCIM externalId cannot be rebound")

    resolved_name = _resolve_display_name(display_name, name)
    now = _utc_now()
    managed.user.full_name = resolved_name
    revoked_sessions = 0
    if managed.user.is_active and not active:
        managed.user.is_active = False
        managed.binding.deactivated_at = now
        revoked_sessions = _revoke_active_user_sessions(db, user=managed.user, now=now)
    elif not managed.user.is_active and active:
        if managed.binding.deactivated_at is None:
            raise PermissionError("A locally suspended User cannot be reactivated through SCIM")
        managed.user.is_active = True
        managed.binding.deactivated_at = None
    managed.binding.last_synced_at = now
    db.flush()
    return managed, revoked_sessions


def deactivate_scim_managed_user(
    db: Session,
    *,
    context: ScimServiceContext,
    user_id: UUID,
) -> tuple[ScimManagedUser, int]:
    if not scim_user_provisioning_is_enabled(context):
        raise PermissionError("SCIM User provisioning capability is disabled")
    managed = get_scim_managed_user(
        db,
        organization_id=context.organization_id,
        user_id=user_id,
        lock=True,
    )
    if managed is None:
        raise LookupError("SCIM managed User not found")
    now = _utc_now()
    revoked_sessions = 0
    if managed.user.is_active:
        managed.user.is_active = False
        managed.binding.deactivated_at = now
        revoked_sessions = _revoke_active_user_sessions(db, user=managed.user, now=now)
    managed.binding.last_synced_at = now
    db.flush()
    return managed, revoked_sessions
