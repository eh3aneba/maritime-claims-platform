from __future__ import annotations

import base64
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.claims.legal_hold_proposals import ingest_legal_hold_proposal
from app.modules.claims.retention_models import LegalHoldProposal
from app.modules.claims.retention_signal_models import PreservationSignalProfile
from app.modules.claims.retention_signal_schemas import PreservationSignalPayload
from app.modules.users.models import User

settings = get_settings()
ALLOWED_HOLD_SOURCES = {"litigation", "regulatory", "investigation"}
PREVIOUS_KEY_GRACE_HOURS = 24
SIGNAL_FRESHNESS_SECONDS = 300


class PreservationSignalAuthError(RuntimeError):
    pass


class PreservationSignalConflictError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _allowed_sources(values: list[str]) -> list[str]:
    normalized = sorted({value.strip().lower() for value in values})
    if not normalized or any(value not in ALLOWED_HOLD_SOURCES for value in normalized):
        raise ValueError("Preservation signal profile contains an unsupported hold source")
    return normalized


def _derive(profile: PreservationSignalProfile, salt: str, version: int) -> str:
    context = (
        f"mcri-preservation-signal|{profile.organization_id}|{profile.id}|v{version}|{salt}"
    ).encode()
    digest = hmac.new(settings.secret_key.encode(), context, sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def derive_active_signal_secret(profile: PreservationSignalProfile) -> str:
    return _derive(profile, profile.secret_salt, profile.secret_version)


def _secret_for_version(
    profile: PreservationSignalProfile, *, version: int, now: datetime
) -> str:
    if version == profile.secret_version:
        return derive_active_signal_secret(profile)
    if (
        version == profile.previous_secret_version
        and profile.previous_secret_salt
        and profile.previous_secret_valid_until
        and _utc(profile.previous_secret_valid_until) >= _utc(now)
    ):
        return _derive(profile, profile.previous_secret_salt, version)
    raise PreservationSignalAuthError("signal_key_version_unavailable")


def get_signal_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
) -> PreservationSignalProfile:
    profile = db.scalar(
        select(PreservationSignalProfile).where(
            PreservationSignalProfile.id == profile_id,
            PreservationSignalProfile.organization_id == organization_id,
        )
    )
    if profile is None:
        raise LookupError("Preservation signal profile not found")
    return profile


def get_signal_profile_public(db: Session, *, profile_id: UUID) -> PreservationSignalProfile:
    profile = db.get(PreservationSignalProfile, profile_id)
    if profile is None:
        raise LookupError("Preservation signal profile not found")
    return profile


def list_signal_profiles(db: Session, *, organization_id: UUID) -> list[PreservationSignalProfile]:
    return list(
        db.scalars(
            select(PreservationSignalProfile)
            .where(PreservationSignalProfile.organization_id == organization_id)
            .order_by(PreservationSignalProfile.created_at.desc(), PreservationSignalProfile.id.desc())
        ).all()
    )


def create_signal_profile(
    db: Session,
    *,
    user: User,
    name: str,
    enabled: bool,
    allowed_hold_sources: list[str],
) -> tuple[PreservationSignalProfile, str]:
    profile = PreservationSignalProfile(
        organization_id=user.organization_id,
        created_by_id=user.id,
        updated_by_id=user.id,
        name=name.strip(),
        enabled=enabled,
        allowed_hold_sources=_allowed_sources(allowed_hold_sources),
        secret_salt=secrets.token_hex(32),
        secret_version=1,
        secret_reference="pending",
    )
    db.add(profile)
    db.flush()
    profile.secret_reference = f"derived-hmac-sha256:{profile.id}:v1"
    return profile, derive_active_signal_secret(profile)


def update_signal_profile(
    profile: PreservationSignalProfile,
    *,
    user: User,
    enabled: bool | None,
    allowed_hold_sources: list[str] | None,
) -> PreservationSignalProfile:
    if enabled is not None:
        profile.enabled = enabled
    if allowed_hold_sources is not None:
        profile.allowed_hold_sources = _allowed_sources(allowed_hold_sources)
    profile.updated_by_id = user.id
    return profile


def rotate_signal_profile_secret(
    profile: PreservationSignalProfile,
    *,
    user: User,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(UTC)
    profile.previous_secret_salt = profile.secret_salt
    profile.previous_secret_version = profile.secret_version
    profile.previous_secret_valid_until = current + timedelta(hours=PREVIOUS_KEY_GRACE_HOURS)
    profile.secret_salt = secrets.token_hex(32)
    profile.secret_version += 1
    profile.secret_reference = f"derived-hmac-sha256:{profile.id}:v{profile.secret_version}"
    profile.rotated_at = current
    profile.updated_by_id = user.id
    return derive_active_signal_secret(profile)


def verify_preservation_signal(
    profile: PreservationSignalProfile,
    *,
    raw_body: bytes,
    timestamp_header: str,
    key_version_header: str,
    signature_header: str,
    now: datetime | None = None,
) -> None:
    if not profile.enabled:
        raise PreservationSignalAuthError("signal_profile_disabled")
    current = now or datetime.now(UTC)
    try:
        timestamp_value = int(timestamp_header)
        version = int(key_version_header)
        occurred_at = datetime.fromtimestamp(timestamp_value, tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise PreservationSignalAuthError("invalid_signal_auth_headers") from exc
    if abs((_utc(current) - occurred_at).total_seconds()) > SIGNAL_FRESHNESS_SECONDS:
        raise PreservationSignalAuthError("signal_timestamp_outside_freshness_window")

    secret = _secret_for_version(profile, version=version, now=current)
    signing_input = (
        timestamp_header.encode("utf-8")
        + b"."
        + key_version_header.encode("utf-8")
        + b"."
        + raw_body
    )
    expected = hmac.new(secret.encode("utf-8"), signing_input, sha256).hexdigest()
    supplied = signature_header.strip().lower()
    if supplied.startswith("sha256="):
        supplied = supplied[7:]
    if len(supplied) != 64 or not hmac.compare_digest(expected, supplied):
        raise PreservationSignalAuthError("invalid_signal_signature")


def normalize_signal_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("Signal id must contain between 1 and 200 characters")
    return normalized


def ingest_signed_preservation_signal(
    db: Session,
    *,
    profile: PreservationSignalProfile,
    signal_id: str,
    payload: PreservationSignalPayload,
) -> tuple[LegalHoldProposal, bool]:
    normalized_signal_id = normalize_signal_id(signal_id)
    if payload.recommended_hold_source not in profile.allowed_hold_sources:
        raise PreservationSignalConflictError("Signal hold source is not allowed by this profile")

    source_reference = f"preservation-signal:{profile.id}:{normalized_signal_id}"
    source_payload = payload.model_dump(mode="json")
    try:
        return ingest_legal_hold_proposal(
            db,
            organization_id=profile.organization_id,
            claim_id=payload.claim_id,
            source_kind="webhook",
            source_reference=source_reference,
            source_payload=source_payload,
            recommended_hold_source=payload.recommended_hold_source,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise PreservationSignalConflictError(str(exc)) from exc
