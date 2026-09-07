import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.auth.models import EnterpriseIdentityProvider
from app.modules.auth.saml_models import SamlAuthnTransaction, SamlTrustRuntimeProfile
from app.modules.auth.saml_trust import get_current_saml_trust_runtime_profile
from app.modules.organizations.models import Organization, OrganizationStatus

SAML_TRANSACTION_TTL_MINUTES = 10


@dataclass(frozen=True)
class SamlAuthnStartMaterial:
    request_id: str
    relay_state: str


@dataclass(frozen=True)
class SamlAuthnTransactionSource:
    provider: EnterpriseIdentityProvider
    profile: SamlTrustRuntimeProfile


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _secret_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


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


def _locked_saml_provider_by_key(
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


def _new_start_material(transaction_id: UUID) -> SamlAuthnStartMaterial:
    request_id = "_" + secrets.token_urlsafe(32)
    relay_secret = secrets.token_urlsafe(24)
    relay_state = f"{transaction_id}.{relay_secret}"
    if len(relay_state.encode("utf-8")) > 80:
        raise RuntimeError("Generated SAML RelayState exceeded the binding limit")
    return SamlAuthnStartMaterial(request_id=request_id, relay_state=relay_state)


def create_saml_authn_transaction(
    db: Session,
    *,
    organization_slug: str,
    provider_key: str,
) -> tuple[
    SamlAuthnTransaction,
    SamlAuthnStartMaterial,
    EnterpriseIdentityProvider,
    SamlTrustRuntimeProfile,
]:
    organization = _active_organization_by_slug(
        db,
        organization_slug=organization_slug,
    )
    if organization is None:
        raise ValueError("SAML provider is unavailable")

    provider = _locked_saml_provider_by_key(
        db,
        organization_id=organization.id,
        provider_key=provider_key,
    )
    if provider is None or provider.protocol != "saml" or not provider.is_enabled:
        raise ValueError("SAML provider is unavailable")

    profile = get_current_saml_trust_runtime_profile(
        db,
        provider_id=provider.id,
        organization_id=organization.id,
    )
    if profile is None:
        raise ValueError("SAML provider is unavailable")

    transaction_id = uuid4()
    material = _new_start_material(transaction_id)
    now = _utc_now()
    transaction = SamlAuthnTransaction(
        id=transaction_id,
        organization_id=organization.id,
        provider_id=provider.id,
        profile_id=profile.id,
        profile_number=profile.profile_number,
        profile_hash=profile.profile_hash,
        request_id_hash=_secret_hash(material.request_id),
        relay_state_hash=_secret_hash(material.relay_state),
        expires_at=now + timedelta(minutes=SAML_TRANSACTION_TTL_MINUTES),
    )
    db.add(transaction)
    db.flush()
    return transaction, material, provider, profile


def transaction_id_from_relay_state(relay_state: str) -> UUID:
    if not relay_state or len(relay_state.encode("utf-8")) > 80:
        raise ValueError("SAML RelayState is invalid")
    transaction_part, separator, secret_part = relay_state.partition(".")
    if not separator or not secret_part or len(secret_part) < 24:
        raise ValueError("SAML RelayState is invalid")
    try:
        return UUID(transaction_part)
    except ValueError as exc:
        raise ValueError("SAML RelayState is invalid") from exc


def _locked_transaction(
    db: Session,
    *,
    transaction_id: UUID,
) -> SamlAuthnTransaction | None:
    return db.scalar(
        select(SamlAuthnTransaction)
        .where(SamlAuthnTransaction.id == transaction_id)
        .with_for_update()
    )


def _validate_transaction_active(transaction: SamlAuthnTransaction) -> None:
    if transaction.cancelled_at is not None:
        raise ValueError("SAML authentication transaction is cancelled")
    if transaction.consumed_at is not None:
        raise ValueError("SAML authentication transaction is already consumed")
    if _as_utc(transaction.expires_at) <= _utc_now():
        raise ValueError("SAML authentication transaction is expired")


def _validate_transaction_source(
    db: Session,
    *,
    transaction: SamlAuthnTransaction,
) -> SamlAuthnTransactionSource:
    provider = db.get(EnterpriseIdentityProvider, transaction.provider_id)
    if (
        provider is None
        or provider.organization_id != transaction.organization_id
        or provider.protocol != "saml"
        or not provider.is_enabled
    ):
        raise ValueError("SAML authentication transaction source is unavailable")

    profile = db.get(SamlTrustRuntimeProfile, transaction.profile_id)
    if (
        profile is None
        or profile.organization_id != transaction.organization_id
        or profile.provider_id != transaction.provider_id
        or profile.profile_number != transaction.profile_number
        or not hmac.compare_digest(profile.profile_hash, transaction.profile_hash)
    ):
        raise ValueError("SAML authentication transaction profile source does not match")

    return SamlAuthnTransactionSource(provider=provider, profile=profile)


def _validate_relay_state(
    transaction: SamlAuthnTransaction,
    *,
    relay_state: str,
) -> None:
    if not relay_state or not hmac.compare_digest(
        transaction.relay_state_hash,
        _secret_hash(relay_state),
    ):
        raise ValueError("SAML authentication transaction proof does not match")


def _validate_request_id(
    transaction: SamlAuthnTransaction,
    *,
    request_id: str,
) -> None:
    if not request_id or not hmac.compare_digest(
        transaction.request_id_hash,
        _secret_hash(request_id),
    ):
        raise ValueError("SAML authentication transaction proof does not match")


def validate_saml_relay_state_source(
    db: Session,
    *,
    relay_state: str,
) -> tuple[SamlAuthnTransaction, SamlAuthnTransactionSource]:
    """Resolve the pinned verification source using only the one-time RelayState proof."""

    transaction_id = transaction_id_from_relay_state(relay_state)
    transaction = db.get(SamlAuthnTransaction, transaction_id)
    if transaction is None:
        raise ValueError("SAML authentication transaction not found")
    _validate_transaction_active(transaction)
    _validate_relay_state(transaction, relay_state=relay_state)
    source = _validate_transaction_source(db, transaction=transaction)
    return transaction, source


def validate_saml_authn_transaction_proof(
    db: Session,
    *,
    relay_state: str,
    request_id: str,
) -> tuple[SamlAuthnTransaction, SamlAuthnTransactionSource]:
    transaction, source = validate_saml_relay_state_source(
        db,
        relay_state=relay_state,
    )
    _validate_request_id(transaction, request_id=request_id)
    return transaction, source


def consume_saml_authn_transaction(
    db: Session,
    *,
    relay_state: str,
    request_id: str,
) -> SamlAuthnTransaction:
    """One-time authority transition after successful signed assertion verification."""

    transaction_id = transaction_id_from_relay_state(relay_state)
    transaction = _locked_transaction(db, transaction_id=transaction_id)
    if transaction is None:
        raise ValueError("SAML authentication transaction not found")

    _validate_transaction_active(transaction)
    _validate_relay_state(transaction, relay_state=relay_state)
    _validate_transaction_source(db, transaction=transaction)
    _validate_request_id(transaction, request_id=request_id)

    transaction.consumed_at = _utc_now()
    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=None,
        action="SAML_AUTHN_TRANSACTION_CONSUMED",
        entity_type="saml_authn_transaction",
        entity_id=transaction.id,
        new_values={
            "provider_id": str(transaction.provider_id),
            "profile_id": str(transaction.profile_id),
            "profile_number": transaction.profile_number,
            "profile_hash": transaction.profile_hash,
        },
    )
    db.flush()
    return transaction


def cancel_saml_authn_transaction(
    db: Session,
    *,
    relay_state: str,
) -> SamlAuthnTransaction:
    transaction_id = transaction_id_from_relay_state(relay_state)
    transaction = _locked_transaction(db, transaction_id=transaction_id)
    if transaction is None:
        raise ValueError("SAML authentication transaction not found")
    _validate_transaction_active(transaction)
    _validate_relay_state(transaction, relay_state=relay_state)

    transaction.cancelled_at = _utc_now()
    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=None,
        action="SAML_AUTHN_TRANSACTION_CANCELLED",
        entity_type="saml_authn_transaction",
        entity_id=transaction.id,
        new_values={
            "provider_id": str(transaction.provider_id),
            "profile_id": str(transaction.profile_id),
            "profile_number": transaction.profile_number,
            "profile_hash": transaction.profile_hash,
        },
    )
    db.flush()
    return transaction
