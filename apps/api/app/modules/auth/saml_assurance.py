import hmac
import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession, EnterpriseIdentityProvider
from app.modules.auth.saml_assurance_models import SamlMfaAssuranceProfile
from app.modules.auth.saml_models import SamlAuthnTransaction, SamlTrustRuntimeProfile
from app.modules.auth.saml_trust import get_current_saml_trust_runtime_profile
from app.modules.users.models import User

SAML_EXTERNAL_MFA_METHOD = "saml_external"
SAML_MFA_EVIDENCE_TYPE = "authn_context"
MAX_ASSURANCE_VALUES = 20
MAX_AUTHN_CONTEXT_LENGTH = 512


@dataclass(frozen=True)
class SamlMfaAssuranceResult:
    verified: bool
    evidence_hash: str | None = None


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_values(values: list[str]) -> list[str]:
    normalized = sorted({value.strip() for value in values if value.strip()})
    if len(normalized) > MAX_ASSURANCE_VALUES:
        raise ValueError("Too many SAML AuthnContext assurance values")
    if any(len(value) > MAX_AUTHN_CONTEXT_LENGTH for value in normalized):
        raise ValueError("SAML AuthnContext assurance value is too long")
    return normalized


def _profile_hash(
    *,
    organization_id: UUID,
    provider_id: UUID,
    saml_profile: SamlTrustRuntimeProfile,
    enabled: bool,
    accepted_authn_context_values: list[str],
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "provider_id": str(provider_id),
        "saml_profile_id": str(saml_profile.id),
        "saml_profile_number": saml_profile.profile_number,
        "saml_profile_hash": saml_profile.profile_hash,
        "enabled": enabled,
        "accepted_authn_context_values": accepted_authn_context_values,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _evidence_hash(value: str) -> str:
    return sha256(f"saml-mfa:authn-context:{value}".encode("utf-8")).hexdigest()


def list_saml_mfa_assurance_profiles(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
) -> list[SamlMfaAssuranceProfile]:
    return list(
        db.scalars(
            select(SamlMfaAssuranceProfile)
            .where(
                SamlMfaAssuranceProfile.organization_id == organization_id,
                SamlMfaAssuranceProfile.provider_id == provider_id,
            )
            .order_by(
                SamlMfaAssuranceProfile.profile_number,
                SamlMfaAssuranceProfile.id,
            )
        )
    )


def get_current_saml_mfa_assurance_profile(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
) -> SamlMfaAssuranceProfile | None:
    return db.scalar(
        select(SamlMfaAssuranceProfile)
        .where(
            SamlMfaAssuranceProfile.organization_id == organization_id,
            SamlMfaAssuranceProfile.provider_id == provider_id,
        )
        .order_by(
            SamlMfaAssuranceProfile.profile_number.desc(),
            SamlMfaAssuranceProfile.id.desc(),
        )
        .limit(1)
    )


def get_current_compatible_saml_mfa_assurance_profile(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
    saml_profile: SamlTrustRuntimeProfile,
) -> SamlMfaAssuranceProfile | None:
    return db.scalar(
        select(SamlMfaAssuranceProfile)
        .where(
            SamlMfaAssuranceProfile.organization_id == organization_id,
            SamlMfaAssuranceProfile.provider_id == provider_id,
            SamlMfaAssuranceProfile.saml_profile_id == saml_profile.id,
            SamlMfaAssuranceProfile.saml_profile_number == saml_profile.profile_number,
            SamlMfaAssuranceProfile.saml_profile_hash == saml_profile.profile_hash,
        )
        .order_by(
            SamlMfaAssuranceProfile.profile_number.desc(),
            SamlMfaAssuranceProfile.id.desc(),
        )
        .limit(1)
    )


def create_saml_mfa_assurance_profile(
    db: Session,
    *,
    provider: EnterpriseIdentityProvider,
    enabled: bool,
    accepted_authn_context_values: list[str],
    created_by_id: UUID,
) -> SamlMfaAssuranceProfile:
    locked_provider = db.scalar(
        select(EnterpriseIdentityProvider)
        .where(EnterpriseIdentityProvider.id == provider.id)
        .with_for_update()
    )
    if locked_provider is None:
        raise ValueError("SAML identity provider no longer exists")
    if locked_provider.organization_id != provider.organization_id:
        raise ValueError("SAML identity provider tenant mismatch")
    if locked_provider.protocol != "saml" or not locked_provider.is_enabled:
        raise ValueError("SAML identity provider must be enabled")

    saml_profile = get_current_saml_trust_runtime_profile(
        db,
        provider_id=locked_provider.id,
        organization_id=locked_provider.organization_id,
    )
    if saml_profile is None:
        raise ValueError("SAML trust/runtime profile is required before assurance configuration")

    normalized = _normalize_values(accepted_authn_context_values)
    if enabled and not normalized:
        raise ValueError("Enabled SAML MFA assurance requires at least one AuthnContext value")

    digest = _profile_hash(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        saml_profile=saml_profile,
        enabled=enabled,
        accepted_authn_context_values=normalized,
    )
    existing = db.scalar(
        select(SamlMfaAssuranceProfile).where(
            SamlMfaAssuranceProfile.provider_id == locked_provider.id,
            SamlMfaAssuranceProfile.profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    current = get_current_saml_mfa_assurance_profile(
        db,
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
    )
    profile = SamlMfaAssuranceProfile(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        saml_profile_id=saml_profile.id,
        saml_profile_number=saml_profile.profile_number,
        saml_profile_hash=saml_profile.profile_hash,
        profile_number=1 if current is None else current.profile_number + 1,
        enabled=enabled,
        accepted_authn_context_values=normalized,
        profile_hash=digest,
        previous_profile_hash=None if current is None else current.profile_hash,
        created_by_id=created_by_id,
    )
    db.add(profile)
    db.flush()
    return profile


def evaluate_saml_mfa_assurance(
    *,
    profile: SamlMfaAssuranceProfile | None,
    authn_context: str | None,
) -> SamlMfaAssuranceResult:
    if profile is None or not profile.enabled or authn_context is None:
        return SamlMfaAssuranceResult(verified=False)
    normalized = authn_context.strip()
    if not normalized or len(normalized) > MAX_AUTHN_CONTEXT_LENGTH:
        return SamlMfaAssuranceResult(verified=False)
    if normalized not in set(profile.accepted_authn_context_values or []):
        return SamlMfaAssuranceResult(verified=False)
    return SamlMfaAssuranceResult(
        verified=True,
        evidence_hash=_evidence_hash(normalized),
    )


def session_has_verified_saml_mfa(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
) -> bool:
    if (
        auth_session.organization_id != user.organization_id
        or auth_session.user_id != user.id
        or auth_session.identity_source != "saml"
        or auth_session.auth_method != "saml"
        or auth_session.mfa_method != SAML_EXTERNAL_MFA_METHOD
        or auth_session.mfa_verified_at is None
        or auth_session.mfa_factor_id is not None
        or auth_session.saml_authn_transaction_id is None
        or auth_session.external_identity_provider_id is None
    ):
        return False

    transaction = db.get(SamlAuthnTransaction, auth_session.saml_authn_transaction_id)
    if (
        transaction is None
        or transaction.organization_id != user.organization_id
        or transaction.provider_id != auth_session.external_identity_provider_id
        or transaction.consumed_at is None
        or transaction.mfa_assurance_verified_at is None
        or transaction.mfa_assurance_evidence_type != SAML_MFA_EVIDENCE_TYPE
        or not transaction.mfa_assurance_evidence_hash
        or transaction.assurance_profile_id is None
        or transaction.assurance_profile_number is None
        or transaction.assurance_profile_hash is None
    ):
        return False

    profile = db.get(SamlMfaAssuranceProfile, transaction.assurance_profile_id)
    if (
        profile is None
        or not profile.enabled
        or profile.organization_id != transaction.organization_id
        or profile.provider_id != transaction.provider_id
        or profile.saml_profile_id != transaction.profile_id
        or profile.saml_profile_number != transaction.profile_number
        or not hmac.compare_digest(profile.saml_profile_hash, transaction.profile_hash)
        or profile.profile_number != transaction.assurance_profile_number
        or not hmac.compare_digest(profile.profile_hash, transaction.assurance_profile_hash)
    ):
        return False
    return True
