import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.connection_authorization_models import (
    ExternalDocumentSourceConnectionAuthorization,
    ExternalDocumentSourceConnectionAuthorizationReceipt,
)
from app.modules.external_document_sources.discovery_service import get_external_document_source_discovery
from app.modules.external_document_sources.models import ExternalDocumentSourceDiscoveryRun, ExternalDocumentSourceProfile
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
)

_REVIEW_TTL = timedelta(minutes=10)
_AUTHORIZATION_TTL = timedelta(minutes=10)
_NON_EXECUTION_FIELDS = (
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
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    return normalized


def _scope_hash(
    *, profile: ExternalDocumentSourceProfile, discovery: ExternalDocumentSourceDiscoveryRun, request_key: str
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(profile.organization_id),
            "profile_id": str(profile.id),
            "provider_kind": profile.provider_kind,
            "profile_hash": profile.profile_hash,
            "discovery_run_id": str(discovery.id),
            "discovery_scope_hash": discovery.scope_hash,
            "discovery_manifest_hash": discovery.manifest_hash,
            "discovery_run_hash": discovery.run_hash,
            "request_key": request_key,
            "execution_limit": 1,
        }
    )


def _request_hash(authorization: ExternalDocumentSourceConnectionAuthorization) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "requested_by_id": str(authorization.requested_by_id),
            "request_reason": authorization.request_reason,
            "requested_at": _iso(authorization.requested_at),
            "review_expires_at": _iso(authorization.review_expires_at),
            "execution_limit": authorization.execution_limit,
            "live_connection_authorized": False,
        }
    )


def _authorization_hash(authorization: ExternalDocumentSourceConnectionAuthorization) -> str:
    if (
        authorization.approved_by_id is None
        or authorization.approved_at is None
        or authorization.approval_reason is None
        or authorization.authorization_expires_at is None
    ):
        raise ExternalDocumentSourceConflictError("External provider connection authorization decision is incomplete")
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "request_hash": authorization.request_hash,
            "approved_by_id": str(authorization.approved_by_id),
            "approved_at": _iso(authorization.approved_at),
            "approval_reason": authorization.approval_reason,
            "authorization_expires_at": _iso(authorization.authorization_expires_at),
            "execution_limit": authorization.execution_limit,
            "live_connection_authorized": True,
        }
    )


def _terminal_hash(authorization: ExternalDocumentSourceConnectionAuthorization) -> str:
    if authorization.terminal_at is None or authorization.terminal_reason is None:
        raise ExternalDocumentSourceConflictError("External provider connection terminal decision is incomplete")
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "request_hash": authorization.request_hash,
            "authorization_hash": authorization.authorization_hash,
            "status": authorization.status,
            "terminal_by_id": str(authorization.terminal_by_id) if authorization.terminal_by_id else None,
            "terminal_at": _iso(authorization.terminal_at),
            "terminal_reason": authorization.terminal_reason,
            "live_connection_authorized": False,
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceConnectionAuthorizationReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "authorization_id": str(receipt.authorization_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "actor_id": str(receipt.actor_id) if receipt.actor_id else None,
            "occurred_at": _iso(receipt.occurred_at),
            "reason": receipt.reason,
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            "prior_receipt_hash": receipt.prior_receipt_hash,
            "live_connection_authorized": receipt.live_connection_authorized,
            **{field: False for field in _NON_EXECUTION_FIELDS},
        }
    )


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceConnectionAuthorization:
    row = db.scalar(
        select(ExternalDocumentSourceConnectionAuthorization).where(
            ExternalDocumentSourceConnectionAuthorization.id == authorization_id,
            ExternalDocumentSourceConnectionAuthorization.organization_id == organization_id,
            ExternalDocumentSourceConnectionAuthorization.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("External provider connection authorization not found")
    return row


def _receipts(
    db: Session, authorization: ExternalDocumentSourceConnectionAuthorization
) -> list[ExternalDocumentSourceConnectionAuthorizationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceConnectionAuthorizationReceipt)
            .where(
                ExternalDocumentSourceConnectionAuthorizationReceipt.organization_id == authorization.organization_id,
                ExternalDocumentSourceConnectionAuthorizationReceipt.authorization_id == authorization.id,
            )
            .order_by(ExternalDocumentSourceConnectionAuthorizationReceipt.sequence_number.asc())
        ).all()
    )


def _lineage(
    db: Session, authorization: ExternalDocumentSourceConnectionAuthorization
) -> tuple[ExternalDocumentSourceProfile, ExternalDocumentSourceDiscoveryRun]:
    profile = get_external_document_source_profile(
        db, organization_id=authorization.organization_id, profile_id=authorization.profile_id
    )
    discovery = get_external_document_source_discovery(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        run_id=authorization.discovery_run_id,
    )
    if (
        authorization.provider_kind != profile.provider_kind
        or authorization.profile_hash != profile.profile_hash
        or authorization.discovery_scope_hash != discovery.scope_hash
        or authorization.discovery_manifest_hash != discovery.manifest_hash
        or authorization.discovery_run_hash != discovery.run_hash
    ):
        raise ExternalDocumentSourceConflictError("External provider connection authorization lineage drifted")
    return profile, discovery


def _expected_events(authorization: ExternalDocumentSourceConnectionAuthorization) -> list[str]:
    if authorization.status == "pending_second_approval":
        return ["requested"]
    if authorization.status == "authorized":
        return ["requested", "authorized"]
    if authorization.status == "rejected":
        return ["requested", "rejected"]
    if authorization.status == "expired":
        return ["requested", "authorized", "expired"] if authorization.authorization_hash else ["requested", "expired"]
    raise ExternalDocumentSourceConflictError("External provider connection authorization status is invalid")


def _expected_receipt_facts(authorization: ExternalDocumentSourceConnectionAuthorization, event_type: str):
    if event_type == "requested":
        return (
            authorization.requested_by_id,
            authorization.requested_at,
            authorization.request_reason,
            "pending_second_approval",
            authorization.request_hash,
            False,
        )
    if event_type == "authorized":
        return (
            authorization.approved_by_id,
            authorization.approved_at,
            authorization.approval_reason,
            "authorized",
            authorization.authorization_hash,
            True,
        )
    if event_type == "rejected":
        return (
            authorization.terminal_by_id,
            authorization.terminal_at,
            authorization.terminal_reason,
            "rejected",
            authorization.terminal_hash,
            False,
        )
    if event_type == "expired":
        return (
            None,
            authorization.terminal_at,
            authorization.terminal_reason,
            "expired",
            authorization.terminal_hash,
            False,
        )
    raise ExternalDocumentSourceConflictError("External provider connection authorization receipt event is invalid")


def _ensure_integrity(db: Session, authorization: ExternalDocumentSourceConnectionAuthorization) -> None:
    profile, discovery = _lineage(db, authorization)
    expected_scope = _scope_hash(profile=profile, discovery=discovery, request_key=authorization.request_key)
    if authorization.scope_hash != expected_scope or authorization.request_hash != _request_hash(authorization):
        raise ExternalDocumentSourceConflictError("External provider connection authorization request integrity failed")
    if _aware(authorization.review_expires_at) != _aware(authorization.requested_at) + _REVIEW_TTL:
        raise ExternalDocumentSourceConflictError("External provider connection authorization review TTL drifted")
    if authorization.execution_limit != 1:
        raise ExternalDocumentSourceConflictError("External provider connection authorization execution boundary drifted")
    if any(bool(getattr(authorization, field)) for field in _NON_EXECUTION_FIELDS):
        raise ExternalDocumentSourceConflictError("External provider connection authorization safety boundary drifted")
    if authorization.live_connection_authorized != (authorization.status == "authorized"):
        raise ExternalDocumentSourceConflictError("External provider connection authorization live-authority mapping drifted")

    if authorization.authorization_hash is not None:
        if authorization.authorization_hash != _authorization_hash(authorization):
            raise ExternalDocumentSourceConflictError("External provider connection authorization decision integrity failed")
        if authorization.approved_at is None or authorization.authorization_expires_at is None:
            raise ExternalDocumentSourceConflictError("External provider connection authorization decision timing is incomplete")
        if _aware(authorization.authorization_expires_at) != _aware(authorization.approved_at) + _AUTHORIZATION_TTL:
            raise ExternalDocumentSourceConflictError("External provider connection authorization execution TTL drifted")
    if authorization.status in {"authorized", "expired"} and authorization.approved_by_id is not None:
        if authorization.requested_by_id == authorization.approved_by_id:
            raise ExternalDocumentSourceConflictError("External provider connection authorization four-eyes boundary drifted")
    if authorization.terminal_hash is not None and authorization.terminal_hash != _terminal_hash(authorization):
        raise ExternalDocumentSourceConflictError("External provider connection authorization terminal integrity failed")

    rows = _receipts(db, authorization)
    events = _expected_events(authorization)
    if len(rows) != len(events) or [row.event_type for row in rows] != events:
        raise ExternalDocumentSourceConflictError("External provider connection authorization receipt lifecycle is incomplete")
    prior: str | None = None
    for expected_sequence, receipt in enumerate(rows, start=1):
        if receipt.sequence_number != expected_sequence or receipt.prior_receipt_hash != prior:
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt chain linkage failed")
        if receipt.scope_hash != authorization.scope_hash:
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt scope drifted")
        if any(bool(getattr(receipt, field)) for field in _NON_EXECUTION_FIELDS):
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt safety boundary drifted")

        expected_actor, expected_time, expected_reason, expected_status, expected_decision, expected_live = _expected_receipt_facts(
            authorization, receipt.event_type
        )
        if expected_time is None or expected_reason is None or expected_decision is None:
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt facts are incomplete")
        if (
            receipt.actor_id != expected_actor
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != expected_reason
            or receipt.status_after != expected_status
        ):
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt facts drifted")
        if receipt.live_connection_authorized != expected_live:
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt authority drifted")
        if receipt.decision_hash != expected_decision:
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt decision drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("External provider connection authorization receipt integrity failed")
        prior = receipt.receipt_hash


def _append_receipt(
    db: Session,
    *,
    authorization: ExternalDocumentSourceConnectionAuthorization,
    event_type: str,
    actor_id: UUID | None,
    occurred_at: datetime,
    reason: str,
    decision_hash: str,
    live_connection_authorized: bool,
) -> None:
    rows = _receipts(db, authorization)
    receipt = ExternalDocumentSourceConnectionAuthorizationReceipt(
        organization_id=authorization.organization_id,
        authorization_id=authorization.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=authorization.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        scope_hash=authorization.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        live_connection_authorized=live_connection_authorized,
        **{field: False for field in _NON_EXECUTION_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _terminalize_expired(
    db: Session,
    authorization: ExternalDocumentSourceConnectionAuthorization,
    *,
    current: datetime,
    reason: str,
) -> None:
    authorization.status = "expired"
    authorization.live_connection_authorized = False
    authorization.terminal_by_id = None
    authorization.terminal_at = current
    authorization.terminal_reason = reason
    authorization.terminal_hash = _terminal_hash(authorization)
    _append_receipt(
        db,
        authorization=authorization,
        event_type="expired",
        actor_id=None,
        occurred_at=current,
        reason=reason,
        decision_hash=authorization.terminal_hash,
        live_connection_authorized=False,
    )
    db.flush()


def _expire_if_needed(
    db: Session,
    authorization: ExternalDocumentSourceConnectionAuthorization,
    *,
    now: datetime,
) -> bool:
    current = _aware(now)
    if authorization.status not in {"pending_second_approval", "authorized"}:
        return False

    profile, _ = _lineage(db, authorization)
    if profile.status != "active":
        _terminalize_expired(
            db,
            authorization,
            current=current,
            reason="Bound external document source profile is no longer active.",
        )
        return True
    if authorization.status == "pending_second_approval" and current >= _aware(authorization.review_expires_at):
        _terminalize_expired(
            db,
            authorization,
            current=current,
            reason="Second-approval review window expired.",
        )
        return True
    if (
        authorization.status == "authorized"
        and authorization.authorization_expires_at is not None
        and current >= _aware(authorization.authorization_expires_at)
    ):
        _terminalize_expired(
            db,
            authorization,
            current=current,
            reason="Bounded provider connection authorization expired unused.",
        )
        return True
    return False


def request_external_document_source_connection_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    discovery_run_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    discovery = get_external_document_source_discovery(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        run_id=discovery_run_id,
    )
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    scope_hash = _scope_hash(profile=profile, discovery=discovery, request_key=normalized_key)

    existing = db.scalar(
        select(ExternalDocumentSourceConnectionAuthorization).where(
            ExternalDocumentSourceConnectionAuthorization.organization_id == organization_id,
            ExternalDocumentSourceConnectionAuthorization.profile_id == profile_id,
            ExternalDocumentSourceConnectionAuthorization.request_key == normalized_key,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        changed = _expire_if_needed(db, existing, now=now or _utc_now())
        if (
            existing.discovery_run_id != discovery_run_id
            or existing.requested_by_id != requested_by_id
            or existing.request_reason != normalized_reason
            or existing.scope_hash != scope_hash
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for external provider connection authorization request_key")
        _ensure_integrity(db, existing)
        return existing, "expired" if changed else "unchanged"

    if profile.status != "active":
        raise ExternalDocumentSourceConflictError("External document source profile must be active before connection authorization")

    requested_at = _aware(now or _utc_now())
    authorization = ExternalDocumentSourceConnectionAuthorization(
        organization_id=organization_id,
        profile_id=profile.id,
        discovery_run_id=discovery.id,
        provider_kind=profile.provider_kind,
        profile_hash=profile.profile_hash,
        discovery_scope_hash=discovery.scope_hash,
        discovery_manifest_hash=discovery.manifest_hash,
        discovery_run_hash=discovery.run_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        execution_limit=1,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        review_expires_at=requested_at + _REVIEW_TTL,
        live_connection_authorized=False,
        **{field: False for field in _NON_EXECUTION_FIELDS},
    )
    db.add(authorization)
    db.flush()
    authorization.request_hash = _request_hash(authorization)
    _append_receipt(
        db,
        authorization=authorization,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=requested_at,
        reason=normalized_reason,
        decision_hash=authorization.request_hash,
        live_connection_authorized=False,
    )
    db.flush()
    _ensure_integrity(db, authorization)
    return authorization, "requested"


def approve_external_document_source_connection_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    normalized_reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    _ensure_integrity(db, authorization)
    current = _aware(now or _utc_now())
    if _expire_if_needed(db, authorization, now=current):
        _ensure_integrity(db, authorization)
        return authorization, "expired"
    if authorization.status == "authorized":
        if authorization.approved_by_id == approved_by_id and authorization.approval_reason == normalized_reason:
            return authorization, "unchanged"
        raise ExternalDocumentSourceConflictError("External provider connection authorization is already approved")
    if authorization.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError("External provider connection authorization is not pending approval")
    if authorization.requested_by_id == approved_by_id:
        raise ExternalDocumentSourceConflictError("Independent second approval is required")

    authorization.status = "authorized"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current
    authorization.approval_reason = normalized_reason
    authorization.authorization_expires_at = current + _AUTHORIZATION_TTL
    authorization.live_connection_authorized = True
    authorization.authorization_hash = _authorization_hash(authorization)
    _append_receipt(
        db,
        authorization=authorization,
        event_type="authorized",
        actor_id=approved_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=authorization.authorization_hash,
        live_connection_authorized=True,
    )
    db.flush()
    _ensure_integrity(db, authorization)
    return authorization, "authorized"


def reject_external_document_source_connection_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    normalized_reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    _ensure_integrity(db, authorization)
    current = _aware(now or _utc_now())
    if _expire_if_needed(db, authorization, now=current):
        _ensure_integrity(db, authorization)
        return authorization, "expired"
    if authorization.status == "rejected":
        if authorization.terminal_by_id == rejected_by_id and authorization.terminal_reason == normalized_reason:
            return authorization, "unchanged"
        raise ExternalDocumentSourceConflictError("External provider connection authorization is already rejected")
    if authorization.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError("External provider connection authorization is not pending rejection")

    authorization.status = "rejected"
    authorization.terminal_by_id = rejected_by_id
    authorization.terminal_at = current
    authorization.terminal_reason = normalized_reason
    authorization.live_connection_authorized = False
    authorization.terminal_hash = _terminal_hash(authorization)
    _append_receipt(
        db,
        authorization=authorization,
        event_type="rejected",
        actor_id=rejected_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=authorization.terminal_hash,
        live_connection_authorized=False,
    )
    db.flush()
    _ensure_integrity(db, authorization)
    return authorization, "rejected"


def get_external_document_source_connection_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
):
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    _ensure_integrity(db, authorization)
    changed = _expire_if_needed(db, authorization, now=_aware(now or _utc_now()))
    _ensure_integrity(db, authorization)
    return authorization, "expired" if changed else "unchanged"


def list_external_document_source_connection_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
):
    authorization, outcome = get_external_document_source_connection_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
        now=now,
    )
    return _receipts(db, authorization), outcome
