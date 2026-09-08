import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.scim_models import ScimProvisioningProfile, ScimProvisioningToken
from app.modules.organizations.models import Organization, OrganizationStatus

SCIM_SERVICE_BASE_PATH = "/api/v1/scim/v2"
MIN_SCIM_TOKEN_TTL_DAYS = 1
MAX_SCIM_TOKEN_TTL_DAYS = 90
SCIM_TOKEN_PREFIX = "mcri_scim_"
SCIM_TOKEN_RANDOM_BYTES = 48

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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _profile_hash(
    *,
    organization_id: UUID,
    client_name: str,
    token_ttl_days: int,
    enabled: bool,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "client_name": client_name,
        "service_base_path": SCIM_SERVICE_BASE_PATH,
        "token_ttl_days": token_ttl_days,
        "enabled": enabled,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _token_digest(plaintext_token: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        plaintext_token.encode("utf-8"),
        sha256,
    ).hexdigest()


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
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
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
