import ipaddress
import json
import re
from hashlib import sha256
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.webauthn_models import WebAuthnRelyingPartyProfile

_RP_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_rp_id(value: str) -> str:
    rp_id = value.strip().lower().rstrip(".")
    if not rp_id or len(rp_id) > 253 or "://" in rp_id or "/" in rp_id or ":" in rp_id:
        raise ValueError("WebAuthn RP ID must be a DNS host without scheme, path or port")
    try:
        ipaddress.ip_address(rp_id)
    except ValueError:
        pass
    else:
        raise ValueError("WebAuthn RP ID must not be an IP address")
    if rp_id != "localhost":
        labels = rp_id.split(".")
        if len(labels) < 2 or any(not _RP_LABEL.fullmatch(label) for label in labels):
            raise ValueError("WebAuthn RP ID must be a valid registrable-style DNS host")
    return rp_id


def _normalize_rp_name(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > 200:
        raise ValueError("WebAuthn RP display name is invalid")
    return normalized


def _normalize_origin(value: str, *, rp_id: str) -> str:
    raw = value.strip()
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("WebAuthn origin is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("WebAuthn origins must be absolute HTTPS origins without path, query or fragment")
    host = parsed.hostname.lower().rstrip(".")
    if host != rp_id and not host.endswith(f".{rp_id}"):
        raise ValueError("WebAuthn origin host must equal the RP ID or be its subdomain")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("WebAuthn origin port is invalid")
    return f"https://{host}" if port in {None, 443} else f"https://{host}:{port}"


def _normalize_origins(values: list[str], *, rp_id: str) -> list[str]:
    normalized = sorted({_normalize_origin(value, rp_id=rp_id) for value in values})
    if not normalized:
        raise ValueError("At least one WebAuthn origin is required")
    if len(normalized) > 10:
        raise ValueError("Too many WebAuthn origins")
    return normalized


def _profile_hash(
    *,
    organization_id: UUID,
    rp_id: str,
    rp_name: str,
    allowed_origins: list[str],
    user_verification: str,
    attestation: str,
) -> str:
    return sha256(
        _canonical_json(
            {
                "organization_id": str(organization_id),
                "rp_id": rp_id,
                "rp_name": rp_name,
                "allowed_origins": allowed_origins,
                "user_verification": user_verification,
                "attestation": attestation,
            }
        ).encode("utf-8")
    ).hexdigest()


def list_webauthn_rp_profiles(
    db: Session,
    *,
    organization_id: UUID,
) -> list[WebAuthnRelyingPartyProfile]:
    return list(
        db.scalars(
            select(WebAuthnRelyingPartyProfile)
            .where(WebAuthnRelyingPartyProfile.organization_id == organization_id)
            .order_by(
                WebAuthnRelyingPartyProfile.profile_number,
                WebAuthnRelyingPartyProfile.id,
            )
        )
    )


def get_current_webauthn_rp_profile(
    db: Session,
    *,
    organization_id: UUID,
) -> WebAuthnRelyingPartyProfile | None:
    return db.scalar(
        select(WebAuthnRelyingPartyProfile)
        .where(WebAuthnRelyingPartyProfile.organization_id == organization_id)
        .order_by(
            WebAuthnRelyingPartyProfile.profile_number.desc(),
            WebAuthnRelyingPartyProfile.id.desc(),
        )
        .limit(1)
    )


def create_webauthn_rp_profile(
    db: Session,
    *,
    organization_id: UUID,
    rp_id: str,
    rp_name: str,
    allowed_origins: list[str],
    user_verification: str,
    attestation: str,
    created_by_id: UUID,
) -> WebAuthnRelyingPartyProfile:
    if user_verification != "required":
        raise ValueError("WebAuthn user verification must be required")
    if attestation != "none":
        raise ValueError("WebAuthn attestation must be none in this phase")

    normalized_rp_id = _normalize_rp_id(rp_id)
    normalized_rp_name = _normalize_rp_name(rp_name)
    normalized_origins = _normalize_origins(allowed_origins, rp_id=normalized_rp_id)
    digest = _profile_hash(
        organization_id=organization_id,
        rp_id=normalized_rp_id,
        rp_name=normalized_rp_name,
        allowed_origins=normalized_origins,
        user_verification=user_verification,
        attestation=attestation,
    )

    existing = db.scalar(
        select(WebAuthnRelyingPartyProfile).where(
            WebAuthnRelyingPartyProfile.organization_id == organization_id,
            WebAuthnRelyingPartyProfile.profile_hash == digest,
        )
    )
    if existing is not None:
        return existing

    current = get_current_webauthn_rp_profile(db, organization_id=organization_id)
    profile = WebAuthnRelyingPartyProfile(
        organization_id=organization_id,
        profile_number=1 if current is None else current.profile_number + 1,
        rp_id=normalized_rp_id,
        rp_name=normalized_rp_name,
        allowed_origins=normalized_origins,
        user_verification=user_verification,
        attestation=attestation,
        profile_hash=digest,
        previous_profile_hash=None if current is None else current.profile_hash,
        created_by_id=created_by_id,
    )
    db.add(profile)
    db.flush()
    return profile
