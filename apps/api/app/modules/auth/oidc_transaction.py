import base64
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.auth.models import (
    EnterpriseIdentityProvider,
    OidcAuthorizationTransaction,
    OidcRuntimeProfile,
    OidcTrustProfile,
)
from app.modules.auth.oidc_runtime import get_current_compatible_oidc_runtime_profile
from app.modules.auth.oidc_trust import get_current_oidc_trust_profile
from app.modules.organizations.models import Organization, OrganizationStatus

OIDC_TRANSACTION_TTL_MINUTES = 10
PKCE_METHOD = "S256"


@dataclass(frozen=True)
class OidcAuthorizationStartMaterial:
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _secret_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _pkce_challenge(code_verifier: str) -> str:
    digest = sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _new_start_material() -> OidcAuthorizationStartMaterial:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    return OidcAuthorizationStartMaterial(
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        code_challenge=_pkce_challenge(code_verifier),
    )


def _active_organization_by_slug(
    db: Session,
    *,
    organization_slug: str,
) -> Organization | None:
    return db.scalar(
        select(Organization).where(
            func.lower(Organization.slug) == organization_slug.strip().lower(),
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
        )
    )


def _locked_oidc_provider_by_key(
    db: Session,
    *,
    organization_id: UUID,
    provider_key: str,
) -> EnterpriseIdentityProvider | None:
    return db.scalar(
        select(EnterpriseIdentityProvider)
        .where(
            EnterpriseIdentityProvider.organization_id == organization_id,
            EnterpriseIdentityProvider.provider_key == provider_key.strip().lower(),
        )
        .with_for_update()
    )


def create_oidc_authorization_transaction(
    db: Session,
    *,
    organization_slug: str,
    provider_key: str,
) -> tuple[
    OidcAuthorizationTransaction,
    OidcAuthorizationStartMaterial,
    EnterpriseIdentityProvider,
    OidcTrustProfile,
    OidcRuntimeProfile,
]:
    organization = _active_organization_by_slug(
        db,
        organization_slug=organization_slug,
    )
    if organization is None:
        raise ValueError("OIDC provider is unavailable")

    provider = _locked_oidc_provider_by_key(
        db,
        organization_id=organization.id,
        provider_key=provider_key,
    )
    if provider is None or provider.protocol != "oidc" or not provider.is_enabled:
        raise ValueError("OIDC provider is unavailable")

    trust_profile = get_current_oidc_trust_profile(
        db,
        provider_id=provider.id,
        organization_id=organization.id,
    )
    if trust_profile is None:
        raise ValueError("OIDC provider is unavailable")

    runtime_profile = get_current_compatible_oidc_runtime_profile(
        db,
        organization_id=organization.id,
        provider_id=provider.id,
        trust_profile=trust_profile,
    )
    if runtime_profile is None:
        raise ValueError("OIDC provider is unavailable")

    material = _new_start_material()
    now = _utc_now()
    transaction = OidcAuthorizationTransaction(
        organization_id=organization.id,
        provider_id=provider.id,
        trust_profile_id=trust_profile.id,
        trust_profile_number=trust_profile.profile_number,
        trust_profile_hash=trust_profile.profile_hash,
        runtime_profile_id=runtime_profile.id,
        runtime_profile_number=runtime_profile.runtime_profile_number,
        runtime_profile_hash=runtime_profile.runtime_profile_hash,
        state_hash=_secret_hash(material.state),
        nonce_hash=_secret_hash(material.nonce),
        pkce_code_challenge=material.code_challenge,
        pkce_method=PKCE_METHOD,
        expires_at=now + timedelta(minutes=OIDC_TRANSACTION_TTL_MINUTES),
    )
    db.add(transaction)
    db.flush()
    return transaction, material, provider, trust_profile, runtime_profile


def _locked_transaction(
    db: Session,
    *,
    transaction_id: UUID,
) -> OidcAuthorizationTransaction | None:
    return db.scalar(
        select(OidcAuthorizationTransaction)
        .where(OidcAuthorizationTransaction.id == transaction_id)
        .with_for_update()
    )


def _validate_transaction_source(
    db: Session,
    *,
    transaction: OidcAuthorizationTransaction,
) -> None:
    provider = db.get(EnterpriseIdentityProvider, transaction.provider_id)
    if (
        provider is None
        or provider.organization_id != transaction.organization_id
        or provider.protocol != "oidc"
        or not provider.is_enabled
    ):
        raise ValueError("OIDC authorization transaction source is unavailable")

    trust_profile = db.get(OidcTrustProfile, transaction.trust_profile_id)
    if (
        trust_profile is None
        or trust_profile.organization_id != transaction.organization_id
        or trust_profile.provider_id != transaction.provider_id
        or trust_profile.profile_number != transaction.trust_profile_number
        or not hmac.compare_digest(
            trust_profile.profile_hash,
            transaction.trust_profile_hash,
        )
    ):
        raise ValueError("OIDC authorization transaction trust source does not match")

    if (
        transaction.runtime_profile_id is None
        or transaction.runtime_profile_number is None
        or transaction.runtime_profile_hash is None
    ):
        raise ValueError("OIDC authorization transaction runtime source is unavailable")

    runtime_profile = db.get(OidcRuntimeProfile, transaction.runtime_profile_id)
    if (
        runtime_profile is None
        or runtime_profile.organization_id != transaction.organization_id
        or runtime_profile.provider_id != transaction.provider_id
        or runtime_profile.trust_profile_id != transaction.trust_profile_id
        or runtime_profile.trust_profile_number != transaction.trust_profile_number
        or not hmac.compare_digest(
            runtime_profile.trust_profile_hash,
            transaction.trust_profile_hash,
        )
        or runtime_profile.runtime_profile_number != transaction.runtime_profile_number
        or not hmac.compare_digest(
            runtime_profile.runtime_profile_hash,
            transaction.runtime_profile_hash,
        )
    ):
        raise ValueError("OIDC authorization transaction runtime source does not match")


def _validate_transaction_active(transaction: OidcAuthorizationTransaction) -> None:
    if transaction.cancelled_at is not None:
        raise ValueError("OIDC authorization transaction is cancelled")
    if transaction.consumed_at is not None:
        raise ValueError("OIDC authorization transaction is already consumed")
    if _as_utc(transaction.expires_at) <= _utc_now():
        raise ValueError("OIDC authorization transaction is expired")


def _require_proof(value: str, *, label: str) -> str:
    if not value:
        raise ValueError(f"OIDC authorization transaction {label} is required")
    return value


def consume_oidc_authorization_transaction(
    db: Session,
    *,
    transaction_id: UUID,
    state: str,
    nonce: str,
    code_verifier: str,
) -> OidcAuthorizationTransaction:
    """Internal one-time primitive for a later callback-verification tranche."""

    state = _require_proof(state, label="state")
    nonce = _require_proof(nonce, label="nonce")
    code_verifier = _require_proof(code_verifier, label="PKCE verifier")

    transaction = _locked_transaction(db, transaction_id=transaction_id)
    if transaction is None:
        raise ValueError("OIDC authorization transaction not found")

    _validate_transaction_active(transaction)
    _validate_transaction_source(db, transaction=transaction)

    if not hmac.compare_digest(transaction.state_hash, _secret_hash(state)):
        raise ValueError("OIDC authorization transaction proof does not match")
    if not hmac.compare_digest(transaction.nonce_hash, _secret_hash(nonce)):
        raise ValueError("OIDC authorization transaction proof does not match")
    if not hmac.compare_digest(
        transaction.pkce_code_challenge,
        _pkce_challenge(code_verifier),
    ):
        raise ValueError("OIDC authorization transaction proof does not match")
    if transaction.pkce_method != PKCE_METHOD:
        raise ValueError("OIDC authorization transaction PKCE method is unsupported")

    transaction.consumed_at = _utc_now()
    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=None,
        action="OIDC_AUTHORIZATION_TRANSACTION_CONSUMED",
        entity_type="oidc_authorization_transaction",
        entity_id=transaction.id,
        new_values={
            "provider_id": str(transaction.provider_id),
            "trust_profile_id": str(transaction.trust_profile_id),
            "trust_profile_number": transaction.trust_profile_number,
            "trust_profile_hash": transaction.trust_profile_hash,
            "runtime_profile_id": str(transaction.runtime_profile_id),
            "runtime_profile_number": transaction.runtime_profile_number,
            "runtime_profile_hash": transaction.runtime_profile_hash,
            "pkce_method": transaction.pkce_method,
        },
    )
    db.flush()
    return transaction


def cancel_oidc_authorization_transaction(
    db: Session,
    *,
    transaction_id: UUID,
    state: str,
) -> OidcAuthorizationTransaction:
    """Internal cancellation primitive requiring possession of the raw state value."""

    state = _require_proof(state, label="state")
    transaction = _locked_transaction(db, transaction_id=transaction_id)
    if transaction is None:
        raise ValueError("OIDC authorization transaction not found")
    _validate_transaction_active(transaction)

    if not hmac.compare_digest(transaction.state_hash, _secret_hash(state)):
        raise ValueError("OIDC authorization transaction proof does not match")

    transaction.cancelled_at = _utc_now()
    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=None,
        action="OIDC_AUTHORIZATION_TRANSACTION_CANCELLED",
        entity_type="oidc_authorization_transaction",
        entity_id=transaction.id,
        new_values={
            "provider_id": str(transaction.provider_id),
            "trust_profile_id": str(transaction.trust_profile_id),
            "trust_profile_number": transaction.trust_profile_number,
            "trust_profile_hash": transaction.trust_profile_hash,
            "runtime_profile_id": (
                None
                if transaction.runtime_profile_id is None
                else str(transaction.runtime_profile_id)
            ),
            "runtime_profile_number": transaction.runtime_profile_number,
            "runtime_profile_hash": transaction.runtime_profile_hash,
            "pkce_method": transaction.pkce_method,
        },
    )
    db.flush()
    return transaction
