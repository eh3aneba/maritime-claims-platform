import json
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlparse
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import EnterpriseIdentityProvider
from app.modules.auth.saml_models import SamlTrustRuntimeProfile

SUPPORTED_SAML_SIGNATURE_ALGORITHMS = {"RSA-SHA256"}
SUPPORTED_SAML_DIGEST_ALGORITHMS = {"SHA-256"}
AUTHN_REQUEST_BINDING = "HTTP-Redirect"
RESPONSE_BINDING = "HTTP-POST"


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_https_url(value: str, *, label: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(
            f"{label} must be an absolute HTTPS endpoint without credentials or fragment"
        )
    return normalized


def _normalize_entity_id(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _normalize_algorithms(
    values: list[str], *, supported: set[str], label: str
) -> list[str]:
    normalized = sorted({value.strip().upper() for value in values if value.strip()})
    if not normalized:
        raise ValueError(f"At least one {label} is required")
    if set(normalized) - supported:
        raise ValueError(f"Unsupported {label}")
    return normalized


def _normalize_signing_certificate(value: str) -> tuple[str, str]:
    normalized_input = value.strip()
    if (
        normalized_input.count("-----BEGIN CERTIFICATE-----") != 1
        or normalized_input.count("-----END CERTIFICATE-----") != 1
        or "PRIVATE KEY" in normalized_input
    ):
        raise ValueError("SAML signing certificate must contain exactly one public X.509 certificate")
    try:
        certificate = x509.load_pem_x509_certificate(normalized_input.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError("SAML signing certificate is not a valid PEM X.509 certificate") from exc

    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise ValueError("SAML signing certificate must contain an RSA public key of at least 2048 bits")

    now = datetime.now(timezone.utc)
    if now < certificate.not_valid_before_utc or now > certificate.not_valid_after_utc:
        raise ValueError("SAML signing certificate is not currently valid")

    normalized_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
    return normalized_pem, fingerprint


def _profile_hash(
    *,
    organization_id: UUID,
    provider_id: UUID,
    idp_entity_identifier: str,
    idp_sso_url: str,
    sp_entity_id: str,
    acs_url: str,
    authn_request_binding: str,
    response_binding: str,
    allowed_signature_algorithms: list[str],
    allowed_digest_algorithms: list[str],
    certificate_sha256: str,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "provider_id": str(provider_id),
        "idp_entity_identifier": idp_entity_identifier,
        "idp_sso_url": idp_sso_url,
        "sp_entity_id": sp_entity_id,
        "acs_url": acs_url,
        "authn_request_binding": authn_request_binding,
        "response_binding": response_binding,
        "allowed_signature_algorithms": allowed_signature_algorithms,
        "allowed_digest_algorithms": allowed_digest_algorithms,
        "certificate_sha256": certificate_sha256,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def get_saml_provider_for_tenant(
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


def _validate_provider(provider: EnterpriseIdentityProvider) -> None:
    if provider.protocol != "saml":
        raise ValueError("SAML trust/runtime profiles require a SAML identity provider")
    if not provider.is_enabled:
        raise ValueError("SAML identity provider must be enabled before profile creation")


def list_saml_trust_runtime_profiles(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> list[SamlTrustRuntimeProfile]:
    return list(
        db.scalars(
            select(SamlTrustRuntimeProfile)
            .where(
                SamlTrustRuntimeProfile.provider_id == provider_id,
                SamlTrustRuntimeProfile.organization_id == organization_id,
            )
            .order_by(
                SamlTrustRuntimeProfile.profile_number,
                SamlTrustRuntimeProfile.id,
            )
        )
    )


def get_current_saml_trust_runtime_profile(
    db: Session,
    *,
    provider_id: UUID,
    organization_id: UUID,
) -> SamlTrustRuntimeProfile | None:
    return db.scalar(
        select(SamlTrustRuntimeProfile)
        .where(
            SamlTrustRuntimeProfile.provider_id == provider_id,
            SamlTrustRuntimeProfile.organization_id == organization_id,
        )
        .order_by(
            SamlTrustRuntimeProfile.profile_number.desc(),
            SamlTrustRuntimeProfile.id.desc(),
        )
        .limit(1)
    )


def create_saml_trust_runtime_profile(
    db: Session,
    *,
    provider: EnterpriseIdentityProvider,
    idp_sso_url: str,
    sp_entity_id: str,
    acs_url: str,
    authn_request_binding: str,
    response_binding: str,
    allowed_signature_algorithms: list[str],
    allowed_digest_algorithms: list[str],
    idp_signing_certificate_pem: str,
    created_by_id: UUID,
) -> SamlTrustRuntimeProfile:
    locked_provider = db.scalar(
        select(EnterpriseIdentityProvider)
        .where(EnterpriseIdentityProvider.id == provider.id)
        .with_for_update()
    )
    if locked_provider is None:
        raise ValueError("SAML identity provider no longer exists")
    if locked_provider.organization_id != provider.organization_id:
        raise ValueError("SAML identity provider tenant mismatch")
    _validate_provider(locked_provider)

    if authn_request_binding != AUTHN_REQUEST_BINDING:
        raise ValueError("Unsupported SAML AuthnRequest binding")
    if response_binding != RESPONSE_BINDING:
        raise ValueError("Unsupported SAML response binding")

    idp_entity_identifier = _normalize_entity_id(
        locked_provider.issuer_identifier,
        label="SAML IdP entity identifier",
    )
    normalized_sso_url = _normalize_https_url(idp_sso_url, label="SAML IdP SSO URL")
    normalized_sp_entity_id = _normalize_entity_id(sp_entity_id, label="SAML SP entity ID")
    normalized_acs_url = _normalize_https_url(acs_url, label="SAML ACS URL")
    normalized_signature_algorithms = _normalize_algorithms(
        allowed_signature_algorithms,
        supported=SUPPORTED_SAML_SIGNATURE_ALGORITHMS,
        label="SAML signature algorithm",
    )
    normalized_digest_algorithms = _normalize_algorithms(
        allowed_digest_algorithms,
        supported=SUPPORTED_SAML_DIGEST_ALGORITHMS,
        label="SAML digest algorithm",
    )
    normalized_certificate, certificate_sha256 = _normalize_signing_certificate(
        idp_signing_certificate_pem
    )

    digest = _profile_hash(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        idp_entity_identifier=idp_entity_identifier,
        idp_sso_url=normalized_sso_url,
        sp_entity_id=normalized_sp_entity_id,
        acs_url=normalized_acs_url,
        authn_request_binding=AUTHN_REQUEST_BINDING,
        response_binding=RESPONSE_BINDING,
        allowed_signature_algorithms=normalized_signature_algorithms,
        allowed_digest_algorithms=normalized_digest_algorithms,
        certificate_sha256=certificate_sha256,
    )

    existing = db.scalar(
        select(SamlTrustRuntimeProfile).where(
            SamlTrustRuntimeProfile.provider_id == locked_provider.id,
            SamlTrustRuntimeProfile.profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    current = get_current_saml_trust_runtime_profile(
        db,
        provider_id=locked_provider.id,
        organization_id=locked_provider.organization_id,
    )
    profile = SamlTrustRuntimeProfile(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        profile_number=1 if current is None else current.profile_number + 1,
        idp_entity_identifier=idp_entity_identifier,
        idp_sso_url=normalized_sso_url,
        sp_entity_id=normalized_sp_entity_id,
        acs_url=normalized_acs_url,
        authn_request_binding=AUTHN_REQUEST_BINDING,
        response_binding=RESPONSE_BINDING,
        allowed_signature_algorithms=normalized_signature_algorithms,
        allowed_digest_algorithms=normalized_digest_algorithms,
        idp_signing_certificate_pem=normalized_certificate,
        certificate_sha256=certificate_sha256,
        profile_hash=digest,
        previous_profile_hash=None if current is None else current.profile_hash,
        created_by_id=created_by_id,
    )
    db.add(profile)
    db.flush()
    return profile
