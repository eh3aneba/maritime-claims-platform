import base64
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import (
    EnterpriseIdentityProvider,
    OidcAuthorizationTransaction,
    OidcTrustProfile,
)
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
    # token_urlsafe(n) draws n random bytes before base64url encoding.
    # 32 bytes gives state/nonce 256 bits of entropy; verifier uses 64 bytes.
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    return OidcAuthorizationStartMaterial(
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        code_challenge=_pkce_challenge(code_verifier),
    )


def _active_organization_by_slug(db: Session, *, organization_slug: str) -> Organization | None:
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
    if (
        provider is None
        or provider.protocol != "oidc"
        or not provider.is_enabled
    ):
        raise ValueError("OIDC provider is unavailable")

    profile = get_current_oidc_trust_profile(
        db,
        provider_id=provider.id,
        organization_id=organization.id,
    )
    if profile is None:
        raise ValueError("OIDC provider is unavailable")

    material = _new_start_material()
    now = _utc_now()
    transaction = OidcAuthorizationTransaction(
        organization_id=organization.id,
        provider_id=provider.id,
        trust_profile_id=profile.id,
        trust_profile_number=profile.profile_number,
        trust_profile_hash=profile.profile_hash,
        state_hash=_secret_hash(material.state),
        nonce_hash=_secret_hash(material.nonce),
        pkce_code_challenge=material.code_challenge,
        pkce_method=PKCE_METHOD,
        expires_at=now + timedelta(minutes=OIDC_TRANSACTION_TTL_MINUTES),
    )
    db.add(transaction)
    db.flush()
    return transaction, material, provider, profile


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

    profile = db.get(OidcTrustProfile, transaction.trust_profile_id)
    if (
        profile is None
        or profile.organization_id != transaction.organization_id
        or profile.provider_id != transaction.provider_id
        or profile.profile_number != transaction.trust_profile_number
        or not hmac.compare_digest(profile.profile_hash, transaction.trust_profile_hash)
    ):
        raise ValueError("OIDC authorization transaction trust source does not match")


def _validate_transaction_active(transaction: OidcAuthorizationTransaction) -> None:
    if transaction.cancelled_at is not None:
        raise ValueError("OIDC authorization transaction is cancelled")
    if transaction.consumed_at is not None:
        raise ValueError("OIDC authorization transaction is already consumed")
    if _as_utc(transaction.expires_at) <= _utc_now():
        raise ValueError("OIDC authorization transaction is expired")


def consume_oidc_authorization_transaction(
    db: Session,
    *,
    transaction_id: UUID,
    state: str,
    nonce: str,
    code_verifier: str,
) -> OidcAuthorizationTransaction:
    """Internal one-time primitive for a later callback-verification tranche."""

    transaction = _locked_transaction(db, transaction_id=transaction_id)
    if transaction is None:
        raise ValueError("OIDC authorization transaction not found")

    _validate_transaction_active(transaction)
    _validate_transaction_source(db, transaction=transaction)

    supplied_state_hash = _secret_hash(state)
    supplied_nonce_hash = _secret_hash(nonce)
    supplied_challenge = _pkce_challenge(code_verifier)
    if not hmac.compare_digest(transaction.state_hash, supplied_state_hash):
        raise ValueError("OIDC authorization transaction proof does not match")
    if not hmac.compare_digest(transaction.nonce_hash, supplied_nonce_hash):
        raise ValueError("OIDC authorization transaction proof does not match")
    if not hmac.compare_digest(transaction.pkce_code_challenge, supplied_challenge):
        raise ValueError("OIDC authorization transaction proof does not match")
    if transaction.pkce_method != PKCE_METHOD:
        raise ValueError("OIDC authorization transaction PKCE method is unsupported")

    transaction.consumed_at = _utc_now()
    db.flush()
    return transaction


def cancel_oidc_authorization_transaction(
    db: Session,
    *,
    transaction_id: UUID,
    state: str,
) -> OidcAuthorizationTransaction:
    """Internal cancellation primitive requiring possession of the raw state value."""

    transaction = _locked_transaction(db, transaction_id=transaction_id)
    if transaction is None:
        raise ValueError("OIDC authorization transaction not found")
    _validate_transaction_active(transaction)

    if not hmac.compare_digest(transaction.state_hash, _secret_hash(state)):
        raise ValueError("OIDC authorization transaction proof does not match")

    transaction.cancelled_at = _utc_now()
    db.flush()
    return transaction
