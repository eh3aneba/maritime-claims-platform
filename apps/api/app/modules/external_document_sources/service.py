import hashlib
import json
import re
from datetime import datetime, timezone
from ipaddress import ip_address
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.models import (
    ExternalDocumentSourceProfile,
    ExternalDocumentSourceProfileReceipt,
)


SUPPORTED_PROVIDERS = frozenset({"sharepoint", "google_drive", "sftp"})
_PROVIDER_FIELDS = {
    "sharepoint": (frozenset({"tenant_domain", "site_id", "library_id"}), frozenset({"tenant_domain", "site_id", "library_id"})),
    "google_drive": (frozenset({"shared_drive_id", "folder_id"}), frozenset({"shared_drive_id"})),
    "sftp": (
        frozenset({"hostname", "port", "remote_root_path", "username", "host_key_fingerprint", "access_mode"}),
        frozenset({"hostname", "port", "remote_root_path", "username", "host_key_fingerprint", "access_mode"}),
    ),
}
_SFTP_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SFTP_HOST_KEY_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
_SAFETY_FIELDS = (
    "credential_stored",
    "oauth_token_exchanged",
    "remote_list_performed",
    "remote_read_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "subscription_created",
    "sync_executed",
    "evidence_admitted",
    "document_created",
    "claim_mutated",
    "live_connection_authorized",
)


class ExternalDocumentSourceError(ValueError):
    pass


class ExternalDocumentSourceValidationError(ExternalDocumentSourceError):
    pass


class ExternalDocumentSourceConflictError(ExternalDocumentSourceError):
    pass


class ExternalDocumentSourceNotFoundError(LookupError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _normalize_sftp_hostname(value) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError("Provider configuration field hostname must be a string")
    hostname = value.strip().lower().rstrip(".")
    if not hostname or len(hostname) > 253:
        raise ExternalDocumentSourceValidationError("Provider configuration field hostname is invalid")
    if any(ord(char) < 33 for char in hostname):
        raise ExternalDocumentSourceValidationError("Provider configuration field hostname is invalid")
    try:
        return str(ip_address(hostname))
    except ValueError:
        labels = hostname.split(".")
        if not labels or any(not _SFTP_DNS_LABEL.fullmatch(label) for label in labels):
            raise ExternalDocumentSourceValidationError("Provider configuration field hostname is invalid")
        return hostname


def _normalize_sftp_port(value) -> int:
    if isinstance(value, bool):
        raise ExternalDocumentSourceValidationError("Provider configuration field port must be an integer")
    if isinstance(value, str):
        if not value.strip().isdigit():
            raise ExternalDocumentSourceValidationError("Provider configuration field port must be an integer")
        port = int(value.strip())
    elif isinstance(value, int):
        port = value
    else:
        raise ExternalDocumentSourceValidationError("Provider configuration field port must be an integer")
    if port < 1 or port > 65535:
        raise ExternalDocumentSourceValidationError("Provider configuration field port must be between 1 and 65535")
    return port


def _normalize_sftp_remote_root(value) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError("Provider configuration field remote_root_path must be a string")
    raw = value.strip()
    if not raw or len(raw) > 512 or not raw.startswith("/") or any(ord(char) < 32 for char in raw):
        raise ExternalDocumentSourceValidationError("Provider configuration field remote_root_path must be an absolute POSIX path")
    segments = raw.split("/")
    if any(segment == ".." for segment in segments):
        raise ExternalDocumentSourceValidationError("Provider configuration field remote_root_path must not contain parent traversal")
    normalized_segments = [segment for segment in segments if segment not in {"", "."}]
    return "/" + "/".join(normalized_segments)


def _normalize_sftp_username(value) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError("Provider configuration field username must be a string")
    username = value.strip()
    if not username or len(username) > 128 or any(ord(char) < 32 for char in username):
        raise ExternalDocumentSourceValidationError("Provider configuration field username is invalid")
    return username


def _normalize_sftp_fingerprint(value) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError("Provider configuration field host_key_fingerprint must be a string")
    fingerprint = value.strip()
    if not _SFTP_HOST_KEY_FINGERPRINT.fullmatch(fingerprint):
        raise ExternalDocumentSourceValidationError(
            "Provider configuration field host_key_fingerprint must be an OpenSSH SHA256 fingerprint"
        )
    return fingerprint


def normalize_provider_config(provider_kind: str, raw_config: dict) -> dict:
    if provider_kind not in SUPPORTED_PROVIDERS:
        raise ExternalDocumentSourceValidationError("Unsupported external document source provider")
    if not isinstance(raw_config, dict):
        raise ExternalDocumentSourceValidationError("Provider configuration must be an object")
    allowed, required = _PROVIDER_FIELDS[provider_kind]
    supplied = set(raw_config)
    extra = supplied - allowed
    if extra:
        raise ExternalDocumentSourceValidationError(
            "Provider configuration contains unsupported or secret-like fields: " + ", ".join(sorted(extra))
        )
    missing = required - supplied
    if missing:
        raise ExternalDocumentSourceValidationError("Provider configuration is missing required fields: " + ", ".join(sorted(missing)))

    if provider_kind == "sftp":
        access_mode = raw_config["access_mode"]
        if not isinstance(access_mode, str) or access_mode.strip().lower() != "read_only":
            raise ExternalDocumentSourceValidationError(
                "Provider configuration field access_mode must be read_only"
            )
        return {
            "access_mode": "read_only",
            "host_key_fingerprint": _normalize_sftp_fingerprint(raw_config["host_key_fingerprint"]),
            "hostname": _normalize_sftp_hostname(raw_config["hostname"]),
            "port": _normalize_sftp_port(raw_config["port"]),
            "remote_root_path": _normalize_sftp_remote_root(raw_config["remote_root_path"]),
            "username": _normalize_sftp_username(raw_config["username"]),
        }

    normalized: dict[str, str] = {}
    for key in sorted(allowed):
        if key not in raw_config or raw_config[key] is None:
            continue
        value = raw_config[key]
        if not isinstance(value, str):
            raise ExternalDocumentSourceValidationError(f"Provider configuration field {key} must be a string")
        value = value.strip()
        if not value:
            if key in required:
                raise ExternalDocumentSourceValidationError(f"Provider configuration field {key} must not be blank")
            continue
        if len(value) > 512:
            raise ExternalDocumentSourceValidationError(f"Provider configuration field {key} is too long")
        normalized[key] = value.lower() if key == "tenant_domain" else value
    if required - set(normalized):
        raise ExternalDocumentSourceValidationError("Provider configuration contains blank required fields")
    return normalized


def _profile_hash(
    *,
    organization_id: UUID,
    provider_kind: str,
    display_name: str,
    config_hash: str,
    requested_by_id: UUID,
    request_reason: str,
    requested_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(organization_id),
            "provider_kind": provider_kind,
            "display_name": display_name,
            "config_hash": config_hash,
            "requested_by_id": str(requested_by_id),
            "request_reason": request_reason,
            "requested_at": _iso(requested_at),
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _approval_hash(profile: ExternalDocumentSourceProfile, *, actor_id: UUID, occurred_at: datetime, reason: str) -> str:
    return _canonical_hash(
        {
            "profile_id": str(profile.id),
            "profile_hash": profile.profile_hash,
            "actor_id": str(actor_id),
            "occurred_at": _iso(occurred_at),
            "reason": reason,
            "status": "active",
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _terminal_hash(profile: ExternalDocumentSourceProfile, *, actor_id: UUID, occurred_at: datetime, reason: str, status: str) -> str:
    return _canonical_hash(
        {
            "profile_id": str(profile.id),
            "profile_hash": profile.profile_hash,
            "approval_hash": profile.approval_hash,
            "actor_id": str(actor_id),
            "occurred_at": _iso(occurred_at),
            "reason": reason,
            "status": status,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _receipt_hash(
    *,
    profile_id: UUID,
    sequence_number: int,
    event_type: str,
    status_after: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    profile_hash: str,
    decision_hash: str | None,
    prior_receipt_hash: str | None,
) -> str:
    return _canonical_hash(
        {
            "profile_id": str(profile_id),
            "sequence_number": sequence_number,
            "event_type": event_type,
            "status_after": status_after,
            "actor_id": str(actor_id),
            "occurred_at": _iso(occurred_at),
            "reason": reason,
            "profile_hash": profile_hash,
            "decision_hash": decision_hash,
            "prior_receipt_hash": prior_receipt_hash,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _stored_profile_integrity_ok(profile: ExternalDocumentSourceProfile) -> bool:
    return profile.profile_hash == _profile_hash(
        organization_id=profile.organization_id,
        provider_kind=profile.provider_kind,
        display_name=profile.display_name,
        config_hash=profile.config_hash,
        requested_by_id=profile.requested_by_id,
        request_reason=profile.request_reason,
        requested_at=profile.requested_at,
    ) and profile.config_hash == _canonical_hash(profile.normalized_config)


def _verify_receipts(db: Session, profile: ExternalDocumentSourceProfile) -> None:
    receipts = list(
        db.scalars(
            select(ExternalDocumentSourceProfileReceipt)
            .where(
                ExternalDocumentSourceProfileReceipt.organization_id == profile.organization_id,
                ExternalDocumentSourceProfileReceipt.profile_id == profile.id,
            )
            .order_by(ExternalDocumentSourceProfileReceipt.sequence_number.asc())
        ).all()
    )
    if not receipts:
        raise ExternalDocumentSourceConflictError("External document source receipt chain is missing")

    prior: str | None = None
    for expected, receipt in enumerate(receipts, start=1):
        if receipt.sequence_number != expected or receipt.prior_receipt_hash != prior:
            raise ExternalDocumentSourceConflictError("External document source receipt chain linkage failed")
        expected_hash = _receipt_hash(
            profile_id=receipt.profile_id,
            sequence_number=receipt.sequence_number,
            event_type=receipt.event_type,
            status_after=receipt.status_after,
            actor_id=receipt.actor_id,
            occurred_at=receipt.occurred_at,
            reason=receipt.reason,
            profile_hash=receipt.profile_hash,
            decision_hash=receipt.decision_hash,
            prior_receipt_hash=receipt.prior_receipt_hash,
        )
        if receipt.receipt_hash != expected_hash or receipt.profile_hash != profile.profile_hash:
            raise ExternalDocumentSourceConflictError("External document source receipt integrity failed")
        if any(bool(getattr(receipt, field)) for field in _SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("External document source receipt safety boundary drifted")
        prior = receipt.receipt_hash

    expected_events = ["requested"]
    if profile.status in {"active", "disabled"}:
        expected_events.append("approved")
    elif profile.status == "rejected":
        expected_events.append("rejected")
    if profile.status == "disabled":
        expected_events.append("disabled")
    if [row.event_type for row in receipts] != expected_events:
        raise ExternalDocumentSourceConflictError("External document source receipt lifecycle is incomplete or inconsistent")
    if receipts[-1].status_after != profile.status:
        raise ExternalDocumentSourceConflictError("External document source receipt terminal status drifted")

    requested = receipts[0]
    if not all(
        (
            requested.status_after == "pending_second_approval",
            requested.actor_id == profile.requested_by_id,
            _iso(requested.occurred_at) == _iso(profile.requested_at),
            requested.reason == profile.request_reason,
            requested.decision_hash is None,
        )
    ):
        raise ExternalDocumentSourceConflictError("External document source request receipt drifted")

    if profile.status in {"active", "disabled"}:
        if any(
            value is None
            for value in (
                profile.approved_by_id,
                profile.approved_at,
                profile.approval_reason,
                profile.approval_hash,
            )
        ):
            raise ExternalDocumentSourceConflictError("External document source approval evidence is incomplete")
        recomputed_approval_hash = _approval_hash(
            profile,
            actor_id=profile.approved_by_id,
            occurred_at=profile.approved_at,
            reason=profile.approval_reason,
        )
        if profile.approval_hash != recomputed_approval_hash:
            raise ExternalDocumentSourceConflictError("External document source approval decision integrity failed")
        approved = receipts[1]
        if not all(
            (
                approved.status_after == "active",
                approved.actor_id == profile.approved_by_id,
                _iso(approved.occurred_at) == _iso(profile.approved_at),
                approved.reason == profile.approval_reason,
                approved.decision_hash == profile.approval_hash,
            )
        ):
            raise ExternalDocumentSourceConflictError("External document source approval receipt drifted")

    if profile.status in {"rejected", "disabled"}:
        if any(
            value is None
            for value in (
                profile.terminal_by_id,
                profile.terminal_at,
                profile.terminal_reason,
                profile.terminal_hash,
            )
        ):
            raise ExternalDocumentSourceConflictError("External document source terminal evidence is incomplete")
        recomputed_terminal_hash = _terminal_hash(
            profile,
            actor_id=profile.terminal_by_id,
            occurred_at=profile.terminal_at,
            reason=profile.terminal_reason,
            status=profile.status,
        )
        if profile.terminal_hash != recomputed_terminal_hash:
            raise ExternalDocumentSourceConflictError("External document source terminal decision integrity failed")
        terminal = receipts[-1]
        if not all(
            (
                terminal.actor_id == profile.terminal_by_id,
                _iso(terminal.occurred_at) == _iso(profile.terminal_at),
                terminal.reason == profile.terminal_reason,
                terminal.decision_hash == profile.terminal_hash,
            )
        ):
            raise ExternalDocumentSourceConflictError("External document source terminal receipt drifted")


def _ensure_profile_integrity(db: Session, profile: ExternalDocumentSourceProfile) -> None:
    if not _stored_profile_integrity_ok(profile):
        raise ExternalDocumentSourceConflictError("External document source profile integrity failed")
    if any(bool(getattr(profile, field)) for field in _SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("External document source profile safety boundary drifted")
    _verify_receipts(db, profile)


def _get_profile(db: Session, *, organization_id: UUID, profile_id: UUID, for_update: bool = False) -> ExternalDocumentSourceProfile:
    stmt = select(ExternalDocumentSourceProfile).where(
        ExternalDocumentSourceProfile.id == profile_id,
        ExternalDocumentSourceProfile.organization_id == organization_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    profile = db.scalar(stmt)
    if profile is None:
        raise ExternalDocumentSourceNotFoundError("External document source profile not found")
    return profile


def _append_receipt(
    db: Session,
    *,
    profile: ExternalDocumentSourceProfile,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    decision_hash: str | None,
) -> ExternalDocumentSourceProfileReceipt:
    latest = db.scalar(
        select(ExternalDocumentSourceProfileReceipt)
        .where(ExternalDocumentSourceProfileReceipt.profile_id == profile.id)
        .order_by(ExternalDocumentSourceProfileReceipt.sequence_number.desc())
        .limit(1)
        .with_for_update()
    )
    sequence = 1 if latest is None else latest.sequence_number + 1
    prior = None if latest is None else latest.receipt_hash
    receipt = ExternalDocumentSourceProfileReceipt(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        sequence_number=sequence,
        event_type=event_type,
        status_after=profile.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        profile_hash=profile.profile_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=prior,
        receipt_hash=_receipt_hash(
            profile_id=profile.id,
            sequence_number=sequence,
            event_type=event_type,
            status_after=profile.status,
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason=reason,
            profile_hash=profile.profile_hash,
            decision_hash=decision_hash,
            prior_receipt_hash=prior,
        ),
        **{field: False for field in _SAFETY_FIELDS},
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_external_document_source_profile(
    db: Session,
    *,
    organization_id: UUID,
    requested_by_id: UUID,
    provider_kind: str,
    display_name: str,
    raw_config: dict,
    request_reason: str,
    now: datetime | None = None,
) -> ExternalDocumentSourceProfile:
    current = now or _utc_now()
    display = _normalize_text(display_name, field="display_name", minimum=3, maximum=200)
    reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    normalized_config = normalize_provider_config(provider_kind, raw_config)
    config_hash = _canonical_hash(normalized_config)
    existing = db.scalar(
        select(ExternalDocumentSourceProfile).where(
            ExternalDocumentSourceProfile.organization_id == organization_id,
            ExternalDocumentSourceProfile.provider_kind == provider_kind,
            ExternalDocumentSourceProfile.config_hash == config_hash,
        )
    )
    if existing is not None:
        _ensure_profile_integrity(db, existing)
        if existing.requested_by_id == requested_by_id and existing.display_name == display and existing.request_reason == reason:
            return existing
        raise ExternalDocumentSourceConflictError("This external document source scope already has a governed profile")

    profile_hash = _profile_hash(
        organization_id=organization_id,
        provider_kind=provider_kind,
        display_name=display,
        config_hash=config_hash,
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current,
    )
    profile = ExternalDocumentSourceProfile(
        organization_id=organization_id,
        provider_kind=provider_kind,
        display_name=display,
        normalized_config=normalized_config,
        config_hash=config_hash,
        profile_hash=profile_hash,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current,
        **{field: False for field in _SAFETY_FIELDS},
    )
    db.add(profile)
    db.flush()
    _append_receipt(
        db,
        profile=profile,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=None,
    )
    return profile


def approve_external_document_source_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    approved_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    current = now or _utc_now()
    reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id, for_update=True)
    _ensure_profile_integrity(db, profile)
    if profile.status == "active":
        if profile.approved_by_id == approved_by_id and profile.approval_reason == reason:
            return profile, "unchanged"
        raise ExternalDocumentSourceConflictError("Conflicting replay for approved external document source profile")
    if profile.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError(f"External document source profile is already terminal:{profile.status}")
    if approved_by_id == profile.requested_by_id:
        raise ExternalDocumentSourceConflictError("External document source profile requires an independent second approver")
    profile.status = "active"
    profile.approved_by_id = approved_by_id
    profile.approved_at = current
    profile.approval_reason = reason
    profile.approval_hash = _approval_hash(profile, actor_id=approved_by_id, occurred_at=current, reason=reason)
    _append_receipt(
        db,
        profile=profile,
        event_type="approved",
        actor_id=approved_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=profile.approval_hash,
    )
    return profile, "approved"


def reject_external_document_source_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    current = now or _utc_now()
    reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id, for_update=True)
    _ensure_profile_integrity(db, profile)
    if profile.status == "rejected":
        if profile.terminal_by_id == rejected_by_id and profile.terminal_reason == reason:
            return profile, "unchanged"
        raise ExternalDocumentSourceConflictError("Conflicting replay for rejected external document source profile")
    if profile.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError(f"External document source profile cannot be rejected from status:{profile.status}")
    if rejected_by_id == profile.requested_by_id:
        raise ExternalDocumentSourceConflictError("External document source profile rejection requires an independent actor")
    profile.status = "rejected"
    profile.terminal_by_id = rejected_by_id
    profile.terminal_at = current
    profile.terminal_reason = reason
    profile.terminal_hash = _terminal_hash(profile, actor_id=rejected_by_id, occurred_at=current, reason=reason, status="rejected")
    _append_receipt(
        db,
        profile=profile,
        event_type="rejected",
        actor_id=rejected_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=profile.terminal_hash,
    )
    return profile, "rejected"


def disable_external_document_source_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    disabled_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    current = now or _utc_now()
    reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id, for_update=True)
    _ensure_profile_integrity(db, profile)
    if profile.status == "disabled":
        if profile.terminal_by_id == disabled_by_id and profile.terminal_reason == reason:
            return profile, "unchanged"
        raise ExternalDocumentSourceConflictError("Conflicting replay for disabled external document source profile")
    if profile.status != "active":
        raise ExternalDocumentSourceConflictError(f"External document source profile cannot be disabled from status:{profile.status}")
    profile.status = "disabled"
    profile.terminal_by_id = disabled_by_id
    profile.terminal_at = current
    profile.terminal_reason = reason
    profile.terminal_hash = _terminal_hash(profile, actor_id=disabled_by_id, occurred_at=current, reason=reason, status="disabled")
    _append_receipt(
        db,
        profile=profile,
        event_type="disabled",
        actor_id=disabled_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=profile.terminal_hash,
    )
    return profile, "disabled"


def get_external_document_source_profile(db: Session, *, organization_id: UUID, profile_id: UUID) -> ExternalDocumentSourceProfile:
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    return profile


def list_external_document_source_profiles(db: Session, *, organization_id: UUID, provider_kind: str | None = None) -> list[ExternalDocumentSourceProfile]:
    if provider_kind is not None and provider_kind not in SUPPORTED_PROVIDERS:
        raise ExternalDocumentSourceValidationError("Unsupported external document source provider")
    stmt = select(ExternalDocumentSourceProfile).where(ExternalDocumentSourceProfile.organization_id == organization_id)
    if provider_kind is not None:
        stmt = stmt.where(ExternalDocumentSourceProfile.provider_kind == provider_kind)
    profiles = list(db.scalars(stmt.order_by(ExternalDocumentSourceProfile.created_at.asc())).all())
    for profile in profiles:
        _ensure_profile_integrity(db, profile)
    return profiles


def list_external_document_source_profile_receipts(db: Session, *, organization_id: UUID, profile_id: UUID) -> list[ExternalDocumentSourceProfileReceipt]:
    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    return list(
        db.scalars(
            select(ExternalDocumentSourceProfileReceipt)
            .where(
                ExternalDocumentSourceProfileReceipt.organization_id == organization_id,
                ExternalDocumentSourceProfileReceipt.profile_id == profile.id,
            )
            .order_by(ExternalDocumentSourceProfileReceipt.sequence_number.asc())
        ).all()
    )
