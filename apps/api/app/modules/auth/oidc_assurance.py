import hmac
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    OidcAuthorizationTransaction,
    OidcTrustProfile,
)
from app.modules.auth.oidc_assurance_models import OidcMfaAssuranceProfile
from app.modules.auth.oidc_trust import get_current_oidc_trust_profile
from app.modules.users.models import User

OIDC_EXTERNAL_MFA_METHOD = "oidc_external"
OIDC_MFA_EVIDENCE_TYPES = {"amr", "acr"}
MAX_ASSURANCE_VALUES = 20
MAX_AMR_VALUE_LENGTH = 64
MAX_ACR_VALUE_LENGTH = 512


@dataclass(frozen=True)
class OidcMfaAssuranceResult:
    verified: bool
    evidence_type: str | None = None
    evidence_hash: str | None = None


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_amr_values(values: list[str]) -> list[str]:
    normalized = sorted({value.strip().lower() for value in values if value.strip()})
    if len(normalized) > MAX_ASSURANCE_VALUES:
        raise ValueError("Too many OIDC AMR assurance values")
    if any(len(value) > MAX_AMR_VALUE_LENGTH for value in normalized):
        raise ValueError("OIDC AMR assurance value is too long")
    return normalized


def _normalize_acr_values(values: list[str]) -> list[str]:
    normalized = sorted({value.strip() for value in values if value.strip()})
    if len(normalized) > MAX_ASSURANCE_VALUES:
        raise ValueError("Too many OIDC ACR assurance values")
    if any(len(value) > MAX_ACR_VALUE_LENGTH for value in normalized):
        raise ValueError("OIDC ACR assurance value is too long")
    return normalized


def _profile_hash(
    *,
    organization_id: UUID,
    provider_id: UUID,
    trust_profile: OidcTrustProfile,
    enabled: bool,
    accepted_amr_values: list[str],
    accepted_acr_values: list[str],
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "provider_id": str(provider_id),
        "trust_profile_id": str(trust_profile.id),
        "trust_profile_number": trust_profile.profile_number,
        "trust_profile_hash": trust_profile.profile_hash,
        "enabled": enabled,
        "accepted_amr_values": accepted_amr_values,
        "accepted_acr_values": accepted_acr_values,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _evidence_hash(*, evidence_type: str, value: str) -> str:
    return sha256(f"oidc-mfa:{evidence_type}:{value}".encode("utf-8")).hexdigest()


def list_oidc_mfa_assurance_profiles(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
) -> list[OidcMfaAssuranceProfile]:
    return list(
        db.scalars(
            select(OidcMfaAssuranceProfile)
            .where(
                OidcMfaAssuranceProfile.organization_id == organization_id,
                OidcMfaAssuranceProfile.provider_id == provider_id,
            )
            .order_by(
                OidcMfaAssuranceProfile.profile_number,
                OidcMfaAssuranceProfile.id,
            )
        )
    )


def get_current_oidc_mfa_assurance_profile(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
) -> OidcMfaAssuranceProfile | None:
    return db.scalar(
        select(OidcMfaAssuranceProfile)
        .where(
            OidcMfaAssuranceProfile.organization_id == organization_id,
            OidcMfaAssuranceProfile.provider_id == provider_id,
        )
        .order_by(
            OidcMfaAssuranceProfile.profile_number.desc(),
            OidcMfaAssuranceProfile.id.desc(),
        )
        .limit(1)
    )


def get_current_compatible_oidc_mfa_assurance_profile(
    db: Session,
    *,
    organization_id: UUID,
    provider_id: UUID,
    trust_profile: OidcTrustProfile,
) -> OidcMfaAssuranceProfile | None:
    return db.scalar(
        select(OidcMfaAssuranceProfile)
        .where(
            OidcMfaAssuranceProfile.organization_id == organization_id,
            OidcMfaAssuranceProfile.provider_id == provider_id,
            OidcMfaAssuranceProfile.trust_profile_id == trust_profile.id,
            OidcMfaAssuranceProfile.trust_profile_number == trust_profile.profile_number,
            OidcMfaAssuranceProfile.trust_profile_hash == trust_profile.profile_hash,
        )
        .order_by(
            OidcMfaAssuranceProfile.profile_number.desc(),
            OidcMfaAssuranceProfile.id.desc(),
        )
        .limit(1)
    )


def create_oidc_mfa_assurance_profile(
    db: Session,
    *,
    provider: EnterpriseIdentityProvider,
    enabled: bool,
    accepted_amr_values: list[str],
    accepted_acr_values: list[str],
    created_by_id: UUID,
) -> OidcMfaAssuranceProfile:
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
        raise ValueError("OIDC trust profile is required before assurance configuration")

    normalized_amr = _normalize_amr_values(accepted_amr_values)
    normalized_acr = _normalize_acr_values(accepted_acr_values)
    if enabled and not normalized_amr and not normalized_acr:
        raise ValueError("Enabled OIDC MFA assurance requires at least one AMR or ACR value")

    digest = _profile_hash(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        trust_profile=trust_profile,
        enabled=enabled,
        accepted_amr_values=normalized_amr,
        accepted_acr_values=normalized_acr,
    )
    existing = db.scalar(
        select(OidcMfaAssuranceProfile).where(
            OidcMfaAssuranceProfile.provider_id == locked_provider.id,
            OidcMfaAssuranceProfile.profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    current = get_current_oidc_mfa_assurance_profile(
        db,
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
    )
    profile = OidcMfaAssuranceProfile(
        organization_id=locked_provider.organization_id,
        provider_id=locked_provider.id,
        trust_profile_id=trust_profile.id,
        trust_profile_number=trust_profile.profile_number,
        trust_profile_hash=trust_profile.profile_hash,
        profile_number=1 if current is None else current.profile_number + 1,
        enabled=enabled,
        accepted_amr_values=normalized_amr,
        accepted_acr_values=normalized_acr,
        profile_hash=digest,
        previous_profile_hash=None if current is None else current.profile_hash,
        created_by_id=created_by_id,
    )
    db.add(profile)
    db.flush()
    return profile


def evaluate_oidc_mfa_assurance(
    *,
    profile: OidcMfaAssuranceProfile | None,
    claims: dict[str, Any],
) -> OidcMfaAssuranceResult:
    if profile is None or not profile.enabled:
        return OidcMfaAssuranceResult(verified=False)

    accepted_amr = set(profile.accepted_amr_values or [])
    raw_amr = claims.get("amr")
    if isinstance(raw_amr, list) and len(raw_amr) <= MAX_ASSURANCE_VALUES:
        normalized_claim_amr: set[str] = set()
        valid_amr = True
        for value in raw_amr:
            if not isinstance(value, str):
                valid_amr = False
                break
            normalized = value.strip().lower()
            if not normalized or len(normalized) > MAX_AMR_VALUE_LENGTH:
                valid_amr = False
                break
            normalized_claim_amr.add(normalized)
        if valid_amr:
            matches = sorted(accepted_amr.intersection(normalized_claim_amr))
            if matches:
                matched = matches[0]
                return OidcMfaAssuranceResult(
                    verified=True,
                    evidence_type="amr",
                    evidence_hash=_evidence_hash(evidence_type="amr", value=matched),
                )

    raw_acr = claims.get("acr")
    if isinstance(raw_acr, str):
        normalized_acr = raw_acr.strip()
        if (
            normalized_acr
            and len(normalized_acr) <= MAX_ACR_VALUE_LENGTH
            and normalized_acr in set(profile.accepted_acr_values or [])
        ):
            return OidcMfaAssuranceResult(
                verified=True,
                evidence_type="acr",
                evidence_hash=_evidence_hash(evidence_type="acr", value=normalized_acr),
            )

    return OidcMfaAssuranceResult(verified=False)


def session_has_verified_oidc_mfa(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
) -> bool:
    if (
        auth_session.organization_id != user.organization_id
        or auth_session.user_id != user.id
        or auth_session.identity_source != "oidc"
        or auth_session.auth_method != "oidc"
        or auth_session.mfa_method != OIDC_EXTERNAL_MFA_METHOD
        or auth_session.mfa_verified_at is None
        or auth_session.mfa_factor_id is not None
        or auth_session.oidc_authorization_transaction_id is None
        or auth_session.external_identity_provider_id is None
    ):
        return False

    transaction = db.get(
        OidcAuthorizationTransaction,
        auth_session.oidc_authorization_transaction_id,
    )
    if (
        transaction is None
        or transaction.organization_id != user.organization_id
        or transaction.provider_id != auth_session.external_identity_provider_id
        or transaction.consumed_at is None
        or transaction.mfa_assurance_verified_at is None
        or transaction.mfa_assurance_evidence_type not in OIDC_MFA_EVIDENCE_TYPES
        or not transaction.mfa_assurance_evidence_hash
        or transaction.assurance_profile_id is None
        or transaction.assurance_profile_number is None
        or transaction.assurance_profile_hash is None
    ):
        return False

    profile = db.get(OidcMfaAssuranceProfile, transaction.assurance_profile_id)
    if (
        profile is None
        or not profile.enabled
        or profile.organization_id != transaction.organization_id
        or profile.provider_id != transaction.provider_id
        or profile.trust_profile_id != transaction.trust_profile_id
        or profile.trust_profile_number != transaction.trust_profile_number
        or not hmac.compare_digest(profile.trust_profile_hash, transaction.trust_profile_hash)
        or profile.profile_number != transaction.assurance_profile_number
        or not hmac.compare_digest(profile.profile_hash, transaction.assurance_profile_hash)
    ):
        return False
    return True
