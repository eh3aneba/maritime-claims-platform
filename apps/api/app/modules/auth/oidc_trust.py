import json
from hashlib import sha256
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import EnterpriseIdentityProvider, OidcTrustProfile

settings = get_settings()
SUPPORTED_OIDC_SIGNING_ALGORITHMS = {"RS256", "ES256"}
_LOCAL_APP_ENVS = {"test", "development", "dev", "local"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _profile_hash(
    *,
    organization_id: UUID,
    provider_id: UUID,
    issuer_identifier: str,
    audience: str,
    jwks_uri: str,
    allowed_algorithms: list[str],
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "provider_id": str(provider_id),
        "issuer_identifier": issuer_identifier,
        "audience": audience,
        "jwks_uri": jwks_uri,
        "allowed_algorithms": allowed_algorithms,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_jwks_uri(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("JWKS URI must be an absolute public endpoint without credentials or fragment")

    if parsed.scheme == "https":
        return normalized

    if (
        settings.app_env.lower() in _LOCAL_APP_ENVS
        and parsed.scheme == "http"
        and parsed.hostname in _LOCAL_HOSTS
    ):
        return normalized

    raise ValueError("JWKS URI must use HTTPS outside explicit local/test contexts")


def _normalize_algorithms(values: list[str]) -> list[str]:
    normalized = sorted({value.strip().upper() for value in values if value.strip()})
    if not normalized:
        raise ValueError("At least one OIDC signing algorithm is required")
    unsupported = set(normalized) - SUPPORTED_OIDC_SIGNING_ALGORITHMS
    if unsupported:
        raise ValueError("Unsupported OIDC signing algorithm")
    return normalized


def get_oidc_provider_for_tenant(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> EnterpriseIdentityProvider | None:
    provider = db.scalar(
        select(EnterpriseIdentityProvider).where(
            EnterpriseIdentityProvider.id == provider_id,
            EnterpriseIdentityProvider.organization_id == organization_id,
        )
    )
    return provider


def _validate_provider(provider: EnterpriseIdentityProvider) -> None:
    if provider.protocol != "oidc":
        raise ValueError("OIDC trust profiles require an OIDC identity provider")
    if not provider.is_enabled:
        raise ValueError("OIDC identity provider must be enabled before trust-profile creation")


def list_oidc_trust_profiles(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> list[OidcTrustProfile]:
    return list(
        db.scalars(
            select(OidcTrustProfile)
            .where(
                OidcTrustProfile.provider_id == provider_id,
                OidcTrustProfile.organization_id == organization_id,
            )
            .order_by(OidcTrustProfile.profile_number, OidcTrustProfile.id)
        )
    )


def get_current_oidc_trust_profile(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> OidcTrustProfile | None:
    return db.scalar(
        select(OidcTrustProfile)
        .where(
            OidcTrustProfile.provider_id == provider_id,
            OidcTrustProfile.organization_id == organization_id,
        )
        .order_by(OidcTrustProfile.profile_number.desc(), OidcTrustProfile.id.desc())
        .limit(1)
    )


def create_oidc_trust_profile(
    db: Session,
    *,
    provider: EnterpriseIdentityProvider,
    audience: str,
    jwks_uri: str,
    allowed_algorithms: list[str],
    created_by_id: UUID,
) -> OidcTrustProfile:
    locked_provider = db.scalar(
        select(EnterpriseIdentityProvider)
        .where(EnterpriseIdentityProvider.id == provider.id)
        .with_for_update()
    )
    if locked_provider is None:
        raise ValueError("OIDC identity provider no longer exists")
    if locked_provider.organization_id != provider.organization_id:
        raise ValueError("OIDC identity provider tenant mismatch")
    _validate_provider(locked_provider)

    normalized_audience = audience.strip()
    if not normalized_audience:
        raise ValueError("OIDC audience/client ID is required")
    normalized_jwks_uri = _normalize_jwks_uri(jwks_uri)
    normalized_algorithms = _normalize_algorithms(allowed_algorithms)
    issuer_identifier = locked_provider.issuer_identifier.strip()

    digest = _profile_hash(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        issuer_identifier=issuer_identifier,
        audience=normalized_audience,
        jwks_uri=normalized_jwks_uri,
        allowed_algorithms=normalized_algorithms,
    )

    existing = db.scalar(
        select(OidcTrustProfile).where(
            OidcTrustProfile.provider_id == locked_provider.id,
            OidcTrustProfile.profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    current = get_current_oidc_trust_profile(
        db,
        provider_id=locked_provider.id,
        organization_id=locked_provider.organization_id,
    )
    profile = OidcTrustProfile(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        profile_number=1 if current is None else current.profile_number + 1,
        issuer_identifier=issuer_identifier,
        audience=normalized_audience,
        jwks_uri=normalized_jwks_uri,
        allowed_algorithms=normalized_algorithms,
        profile_hash=digest,
        previous_profile_hash=None if current is None else current.profile_hash,
        created_by_id=created_by_id,
    )
    db.add(profile)
    db.flush()
    return profile
