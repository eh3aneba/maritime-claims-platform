import json
from hashlib import sha256
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import (
    EnterpriseIdentityProvider,
    OidcRuntimeProfile,
    OidcTrustProfile,
)
from app.modules.auth.oidc_trust import get_current_oidc_trust_profile

settings = get_settings()
_LOCAL_APP_ENVS = {"test", "development", "dev", "local"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_ALLOWED_SCOPES = {"openid", "profile", "email"}
_ALLOWED_CLIENT_AUTH_METHODS = {"none", "client_secret_basic"}


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _runtime_profile_hash(
    *,
    organization_id: UUID,
    provider_id: UUID,
    trust_profile_id: UUID,
    trust_profile_number: int,
    trust_profile_hash: str,
    authorization_endpoint: str,
    token_endpoint: str,
    redirect_uri: str,
    scopes: list[str],
    client_auth_method: str,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "provider_id": str(provider_id),
        "trust_profile_id": str(trust_profile_id),
        "trust_profile_number": trust_profile_number,
        "trust_profile_hash": trust_profile_hash,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "redirect_uri": redirect_uri,
        "scopes": scopes,
        "client_auth_method": client_auth_method,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_https_uri(value: str, *, label: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f"{label} must be an absolute endpoint without credentials or fragment")
    if parsed.scheme == "https":
        return normalized
    if (
        settings.app_env.lower() in _LOCAL_APP_ENVS
        and parsed.scheme == "http"
        and parsed.hostname in _LOCAL_HOSTS
    ):
        return normalized
    raise ValueError(f"{label} must use HTTPS outside explicit local/test contexts")


def _normalize_scopes(values: list[str]) -> list[str]:
    normalized = sorted({value.strip().lower() for value in values if value.strip()})
    if "openid" not in normalized:
        raise ValueError("OIDC runtime scopes must include openid")
    unsupported = set(normalized) - _ALLOWED_SCOPES
    if unsupported:
        raise ValueError("Unsupported OIDC runtime scope")
    return normalized


def _normalize_client_auth_method(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_CLIENT_AUTH_METHODS:
        raise ValueError("Unsupported OIDC client authentication method")
    return normalized


def list_oidc_runtime_profiles(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
) -> list[OidcRuntimeProfile]:
    return list(
        db.scalars(
            select(OidcRuntimeProfile)
            .where(
                OidcRuntimeProfile.organization_id == organization_id,
                OidcRuntimeProfile.provider_id == provider_id,
            )
            .order_by(
                OidcRuntimeProfile.runtime_profile_number,
                OidcRuntimeProfile.id,
            )
        )
    )


def get_current_compatible_oidc_runtime_profile(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
    trust_profile: OidcTrustProfile | None = None,
) -> OidcRuntimeProfile | None:
    source = trust_profile or get_current_oidc_trust_profile(
        db,
        provider_id=provider_id,
        organization_id=organization_id,
    )
    if source is None:
        return None
    return db.scalar(
        select(OidcRuntimeProfile)
        .where(
            OidcRuntimeProfile.organization_id == organization_id,
            OidcRuntimeProfile.provider_id == provider_id,
            OidcRuntimeProfile.trust_profile_id == source.id,
            OidcRuntimeProfile.trust_profile_number == source.profile_number,
            OidcRuntimeProfile.trust_profile_hash == source.profile_hash,
        )
        .order_by(
            OidcRuntimeProfile.runtime_profile_number.desc(),
            OidcRuntimeProfile.id.desc(),
        )
        .limit(1)
    )


def create_oidc_runtime_profile(
    db: Session,
    *,
    provider: EnterpriseIdentityProvider,
    authorization_endpoint: str,
    token_endpoint: str,
    redirect_uri: str,
    scopes: list[str],
    client_auth_method: str,
    created_by_id: UUID,
) -> OidcRuntimeProfile:
    locked_provider = db.scalar(
        select(EnterpriseIdentityProvider)
        .where(EnterpriseIdentityProvider.id == provider.id)
        .with_for_update()
    )
    if locked_provider is None:
        raise ValueError("OIDC identity provider no longer exists")
    if locked_provider.organization_id != provider.organization_id:
        raise ValueError("OIDC identity provider tenant mismatch")
    if locked_provider.protocol != "oidc" or not locked_provider.is_enabled:
        raise ValueError("OIDC identity provider must be enabled")

    trust_profile = get_current_oidc_trust_profile(
        db,
        provider_id=locked_provider.id,
        organization_id=locked_provider.organization_id,
    )
    if trust_profile is None:
        raise ValueError("Current OIDC trust profile is required")

    normalized_authorization = _normalize_https_uri(
        authorization_endpoint,
        label="OIDC authorization endpoint",
    )
    normalized_token = _normalize_https_uri(
        token_endpoint,
        label="OIDC token endpoint",
    )
    normalized_redirect = _normalize_https_uri(
        redirect_uri,
        label="OIDC redirect URI",
    )
    normalized_scopes = _normalize_scopes(scopes)
    normalized_auth_method = _normalize_client_auth_method(client_auth_method)

    digest = _runtime_profile_hash(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        trust_profile_id=trust_profile.id,
        trust_profile_number=trust_profile.profile_number,
        trust_profile_hash=trust_profile.profile_hash,
        authorization_endpoint=normalized_authorization,
        token_endpoint=normalized_token,
        redirect_uri=normalized_redirect,
        scopes=normalized_scopes,
        client_auth_method=normalized_auth_method,
    )

    existing = db.scalar(
        select(OidcRuntimeProfile).where(
            OidcRuntimeProfile.provider_id == locked_provider.id,
            OidcRuntimeProfile.runtime_profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    previous = db.scalar(
        select(OidcRuntimeProfile)
        .where(OidcRuntimeProfile.provider_id == locked_provider.id)
        .order_by(
            OidcRuntimeProfile.runtime_profile_number.desc(),
            OidcRuntimeProfile.id.desc(),
        )
        .limit(1)
    )
    runtime_profile = OidcRuntimeProfile(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        trust_profile_id=trust_profile.id,
        trust_profile_number=trust_profile.profile_number,
        trust_profile_hash=trust_profile.profile_hash,
        runtime_profile_number=1 if previous is None else previous.runtime_profile_number + 1,
        authorization_endpoint=normalized_authorization,
        token_endpoint=normalized_token,
        redirect_uri=normalized_redirect,
        scopes=normalized_scopes,
        client_auth_method=normalized_auth_method,
        runtime_profile_hash=digest,
        previous_runtime_profile_hash=(
            None if previous is None else previous.runtime_profile_hash
        ),
        created_by_id=created_by_id,
    )
    db.add(runtime_profile)
    db.flush()
    return runtime_profile
