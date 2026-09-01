from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import secrets
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai_operations.service import content_free_events_for_delivery
from app.modules.audit.service import write_audit_log
from app.modules.governance_webhooks.models import (
    GovernanceWebhookDelivery,
    GovernanceWebhookDestination,
)
from app.modules.users.models import User

settings = get_settings()

ENVELOPE_VERSION = "2026-09-01.1"
ALLOWED_EVENT_TYPES = {
    "ai_operations.document_processing",
    "ai_operations.claim_qa_synthesis",
}
DELIVERY_STATUSES = {"queued", "attempting", "failed", "delivered", "dead_letter"}
DEFAULT_PREVIOUS_KEY_GRACE_HOURS = 24


class DestinationSecurityError(RuntimeError):
    pass


class SigningKeyUnavailable(RuntimeError):
    pass


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_json(payload: dict) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_event_types(values: list[str]) -> list[str]:
    normalized = sorted(set(values))
    if not normalized or any(value not in ALLOWED_EVENT_TYPES for value in normalized):
        raise HTTPException(422, "Webhook event_types must use the Phase 12I allowlist")
    return normalized


def _host_is_forbidden(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_global


def validate_destination_url(endpoint_url: str) -> str:
    value = endpoint_url.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Invalid webhook destination URL") from exc
    if parsed.scheme.lower() != "https":
        raise HTTPException(422, "Webhook destinations must use HTTPS")
    if not parsed.hostname:
        raise HTTPException(422, "Webhook destination must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(422, "Webhook destination credentials are not permitted in URLs")
    if parsed.fragment:
        raise HTTPException(422, "Webhook destination fragments are not permitted")
    if _host_is_forbidden(parsed.hostname):
        raise HTTPException(422, "Loopback/private/local webhook destinations are blocked")
    if port is not None and not 1 <= port <= 65535:
        raise HTTPException(422, "Webhook destination port is invalid")
    return value


def _ensure_resolved_public_destination(endpoint_url: str) -> None:
    parsed = urlsplit(endpoint_url)
    hostname = parsed.hostname
    if hostname is None:
        raise DestinationSecurityError("destination_hostname_missing")
    if _host_is_forbidden(hostname):
        raise DestinationSecurityError("destination_private_address")
    port = parsed.port or 443
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DestinationSecurityError("destination_dns_error") from exc
    if not resolved:
        raise DestinationSecurityError("destination_dns_empty")
    for item in resolved:
        address = item[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise DestinationSecurityError("destination_dns_invalid_address") from exc
        if not ip.is_global:
            raise DestinationSecurityError("destination_dns_resolved_private")


def _derive_secret_from_salt(destination: GovernanceWebhookDestination, salt: str, version: int) -> str:
    context = (
        f"mcri-governance-webhook|{destination.organization_id}|{destination.id}|v{version}|{salt}"
    ).encode("utf-8")
    digest = hmac.new(settings.secret_key.encode("utf-8"), context, sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def derive_active_signing_secret(destination: GovernanceWebhookDestination) -> str:
    return _derive_secret_from_salt(destination, destination.secret_salt, destination.secret_version)


def _secret_for_delivery(
    destination: GovernanceWebhookDestination,
    secret_version: int,
    *,
    now: datetime,
) -> str:
    if secret_version == destination.secret_version:
        return derive_active_signing_secret(destination)
    if (
        destination.previous_secret_version == secret_version
        and destination.previous_secret_salt
        and destination.previous_secret_valid_until is not None
        and _as_utc(destination.previous_secret_valid_until) >= _as_utc(now)
    ):
        return _derive_secret_from_salt(
            destination,
            destination.previous_secret_salt,
            destination.previous_secret_version,
        )
    raise SigningKeyUnavailable("signing_key_version_unavailable")


def get_destination(
    db: Session,
    organization_id: UUID,
    destination_id: UUID,
) -> GovernanceWebhookDestination:
    row = db.scalar(
        select(GovernanceWebhookDestination).where(
            GovernanceWebhookDestination.id == destination_id,
            GovernanceWebhookDestination.organization_id == organization_id,
        )
    )
    if row is None:
        raise HTTPException(404, "Governance webhook destination not found")
    return row


def list_destinations(db: Session, organization_id: UUID) -> list[GovernanceWebhookDestination]:
    return list(
        db.scalars(
            select(GovernanceWebhookDestination)
            .where(GovernanceWebhookDestination.organization_id == organization_id)
            .order_by(GovernanceWebhookDestination.created_at.desc(), GovernanceWebhookDestination.id.desc())
        )
    )


def create_destination(
    db: Session,
    user: User,
    *,
    name: str,
    endpoint_url: str,
    event_types: list[str],
    enabled: bool,
) -> tuple[GovernanceWebhookDestination, str]:
    destination = GovernanceWebhookDestination(
        organization_id=user.organization_id,
        created_by_id=user.id,
        updated_by_id=user.id,
        name=name.strip(),
        endpoint_url=validate_destination_url(endpoint_url),
        enabled=enabled,
        event_types=_normalize_event_types(event_types),
        secret_salt=secrets.token_hex(32),
        secret_version=1,
        secret_reference="pending",
    )
    db.add(destination)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A webhook destination with this name already exists") from exc
    destination.secret_reference = f"derived-hmac-sha256:{destination.id}:v{destination.secret_version}"
    signing_secret = derive_active_signing_secret(destination)
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="CREATE_GOVERNANCE_WEBHOOK_DESTINATION",
        entity_type="governance_webhook_destination",
        entity_id=destination.id,
        new_values={
            "name": destination.name,
            "endpoint_url": destination.endpoint_url,
            "enabled": destination.enabled,
            "event_types": destination.event_types,
            "secret_version": destination.secret_version,
            "secret_material_persisted": False,
        },
        details="Phase 12I content-free outbound governance destination created by an authorized admin.",
    )
    db.commit()
    db.refresh(destination)
    return destination, signing_secret


def update_destination(
    db: Session,
    user: User,
    destination_id: UUID,
    *,
    name: str | None = None,
    endpoint_url: str | None = None,
    event_types: list[str] | None = None,
    enabled: bool | None = None,
) -> GovernanceWebhookDestination:
    destination = get_destination(db, user.organization_id, destination_id)
    old_values = {
        "name": destination.name,
        "endpoint_url": destination.endpoint_url,
        "enabled": destination.enabled,
        "event_types": destination.event_types,
    }
    if name is not None:
        destination.name = name.strip()
    if endpoint_url is not None:
        destination.endpoint_url = validate_destination_url(endpoint_url)
    if event_types is not None:
        destination.event_types = _normalize_event_types(event_types)
    if enabled is not None:
        destination.enabled = enabled
    destination.updated_by_id = user.id
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="UPDATE_GOVERNANCE_WEBHOOK_DESTINATION",
        entity_type="governance_webhook_destination",
        entity_id=destination.id,
        old_values=old_values,
        new_values={
            "name": destination.name,
            "endpoint_url": destination.endpoint_url,
            "enabled": destination.enabled,
            "event_types": destination.event_types,
        },
        details="Phase 12I destination configuration changed by an authorized admin.",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A webhook destination with this name already exists") from exc
    db.refresh(destination)
    return destination


def rotate_destination_secret(
    db: Session,
    user: User,
    destination_id: UUID,
) -> tuple[GovernanceWebhookDestination, str]:
    destination = get_destination(db, user.organization_id, destination_id)
    now = datetime.now(UTC)
    destination.previous_secret_salt = destination.secret_salt
    destination.previous_secret_version = destination.secret_version
    destination.previous_secret_valid_until = now + timedelta(hours=DEFAULT_PREVIOUS_KEY_GRACE_HOURS)
    destination.secret_salt = secrets.token_hex(32)
    destination.secret_version += 1
    destination.secret_reference = f"derived-hmac-sha256:{destination.id}:v{destination.secret_version}"
    destination.rotated_at = now
    destination.updated_by_id = user.id
    signing_secret = derive_active_signing_secret(destination)
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="ROTATE_GOVERNANCE_WEBHOOK_SECRET",
        entity_type="governance_webhook_destination",
        entity_id=destination.id,
        new_values={
            "secret_version": destination.secret_version,
            "previous_secret_valid_until": destination.previous_secret_valid_until.isoformat(),
            "secret_material_persisted": False,
        },
        details="Phase 12I signing secret rotated; only derived key version metadata was persisted.",
    )
    db.commit()
    db.refresh(destination)
    return destination, signing_secret


def _safe_scalar(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


SOURCE_ALLOWLIST = (
    "workflow_type",
    "claim_id",
    "document_id",
    "document_type",
    "authorization_id",
    "authorization_hash",
    "eligibility_decision_id",
    "eligibility_policy_hash",
    "eligibility_decision_hash",
    "status",
    "failure_code",
    "fallback_used",
    "provider_call_made",
    "provider",
    "model",
    "prompt_bundle_version",
    "schema_bundle_version",
    "human_review_state",
    "human_review_action",
    "requested_by_id",
    "reviewed_by_id",
    "run_hash",
    "review_hash",
    "retrieval_run_id",
    "question_hash",
    "result_set_hash",
    "input_hash",
    "output_hash",
    "answer_hash",
    "source_count",
    "output_candidate_count",
    "human_edit_count",
    "unsupported_output_count",
    "source_grounded_output_count",
    "source_grounding_total_count",
    "input_chars",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "latency_ms",
    "observed_provider_cost_microusd",
    "requires_attention",
    "attention_reasons",
    "content_free",
)


def _source_projection(event: dict) -> dict:
    projection: dict = {}
    for key in SOURCE_ALLOWLIST:
        value = event.get(key)
        if isinstance(value, list):
            projection[key] = [_safe_scalar(item) for item in value]
        else:
            projection[key] = _safe_scalar(value)
    projection["source_event_id"] = str(event["id"])
    projection["source_event_time"] = _safe_scalar(event["event_time"])
    return projection


def _event_type(event: dict) -> str:
    workflow = event["workflow_type"]
    event_type = f"ai_operations.{workflow}"
    if event_type not in ALLOWED_EVENT_TYPES:
        raise RuntimeError("unsupported_governance_event_type")
    return event_type


def _build_envelope(
    *,
    delivery_id: UUID,
    organization_id: UUID,
    event_type: str,
    event: dict,
    emitted_at: datetime,
) -> dict:
    return {
        "version": ENVELOPE_VERSION,
        "event_id": str(delivery_id),
        "event_type": event_type,
        "occurred_at": _safe_scalar(event["event_time"]),
        "emitted_at": _safe_scalar(emitted_at),
        "organization_id": str(organization_id),
        "source": {
            "workflow_type": event["workflow_type"],
            "event_id": str(event["id"]),
        },
        "governance": _source_projection(event),
        "content_free": True,
        "raw_claim_or_model_content_included": False,
        "inbound_command": False,
    }


def sync_content_free_ai_events(db: Session) -> dict:
    destinations = list(
        db.scalars(
            select(GovernanceWebhookDestination)
            .where(GovernanceWebhookDestination.enabled.is_(True))
            .order_by(GovernanceWebhookDestination.organization_id, GovernanceWebhookDestination.id)
        )
    )
    by_org: dict[UUID, list[dict]] = {}
    created = 0
    duplicates = 0
    now = datetime.now(UTC)
    for destination in destinations:
        events = by_org.get(destination.organization_id)
        if events is None:
            events = content_free_events_for_delivery(db, destination.organization_id)
            by_org[destination.organization_id] = events
        for event in events:
            event_type = _event_type(event)
            if event_type not in destination.event_types:
                continue
            projection = _source_projection(event)
            revision_hash = _hash_json(projection)
            existing = db.scalar(
                select(GovernanceWebhookDelivery.id).where(
                    GovernanceWebhookDelivery.destination_id == destination.id,
                    GovernanceWebhookDelivery.source_workflow_type == event["workflow_type"],
                    GovernanceWebhookDelivery.source_event_id == event["id"],
                    GovernanceWebhookDelivery.source_revision_hash == revision_hash,
                    GovernanceWebhookDelivery.envelope_version == ENVELOPE_VERSION,
                )
            )
            if existing is not None:
                duplicates += 1
                continue
            delivery_id = uuid4()
            envelope = _build_envelope(
                delivery_id=delivery_id,
                organization_id=destination.organization_id,
                event_type=event_type,
                event=event,
                emitted_at=now,
            )
            delivery = GovernanceWebhookDelivery(
                id=delivery_id,
                organization_id=destination.organization_id,
                destination_id=destination.id,
                source_workflow_type=event["workflow_type"],
                source_event_id=event["id"],
                source_revision_hash=revision_hash,
                event_type=event_type,
                envelope_version=ENVELOPE_VERSION,
                occurred_at=_as_utc(event["event_time"]),
                envelope=envelope,
                payload_hash=_hash_json(envelope),
                secret_version=destination.secret_version,
                status="queued",
                attempt_count=0,
                max_attempts=settings.governance_webhook_max_attempts,
                manual_retry_count=0,
                next_attempt_at=now,
            )
            try:
                with db.begin_nested():
                    db.add(delivery)
                    db.flush()
                created += 1
            except IntegrityError:
                duplicates += 1
    db.commit()
    return {
        "destinations_scanned": len(destinations),
        "source_events_scanned": sum(len(events) for events in by_org.values()),
        "deliveries_created": created,
        "duplicates_skipped": duplicates,
    }


def enqueue_test_delivery(
    db: Session,
    user: User,
    destination_id: UUID,
) -> GovernanceWebhookDelivery:
    destination = get_destination(db, user.organization_id, destination_id)
    now = datetime.now(UTC)
    source_event_id = uuid4()
    delivery_id = uuid4()
    safe_event = {
        "id": source_event_id,
        "event_time": now,
        "workflow_type": "test",
        "claim_id": None,
        "document_id": None,
        "document_type": None,
        "authorization_id": None,
        "authorization_hash": None,
        "eligibility_decision_id": None,
        "eligibility_policy_hash": None,
        "eligibility_decision_hash": None,
        "status": "synthetic_test",
        "failure_code": None,
        "fallback_used": False,
        "provider_call_made": False,
        "provider": None,
        "model": None,
        "prompt_bundle_version": None,
        "schema_bundle_version": None,
        "human_review_state": "not_applicable",
        "human_review_action": None,
        "requested_by_id": user.id,
        "reviewed_by_id": None,
        "run_hash": None,
        "review_hash": None,
        "retrieval_run_id": None,
        "question_hash": None,
        "result_set_hash": None,
        "input_hash": None,
        "output_hash": None,
        "answer_hash": None,
        "source_count": None,
        "output_candidate_count": None,
        "human_edit_count": None,
        "unsupported_output_count": None,
        "source_grounded_output_count": None,
        "source_grounding_total_count": None,
        "input_chars": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "latency_ms": None,
        "observed_provider_cost_microusd": None,
        "requires_attention": False,
        "attention_reasons": [],
        "content_free": True,
    }
    projection = _source_projection(safe_event)
    envelope = {
        "version": ENVELOPE_VERSION,
        "event_id": str(delivery_id),
        "event_type": "governance_webhook.test",
        "occurred_at": now.isoformat(),
        "emitted_at": now.isoformat(),
        "organization_id": str(user.organization_id),
        "source": {"workflow_type": "test", "event_id": str(source_event_id)},
        "governance": projection,
        "content_free": True,
        "raw_claim_or_model_content_included": False,
        "inbound_command": False,
    }
    delivery = GovernanceWebhookDelivery(
        id=delivery_id,
        organization_id=user.organization_id,
        destination_id=destination.id,
        source_workflow_type="test",
        source_event_id=source_event_id,
        source_revision_hash=_hash_json(projection),
        event_type="governance_webhook.test",
        envelope_version=ENVELOPE_VERSION,
        occurred_at=now,
        envelope=envelope,
        payload_hash=_hash_json(envelope),
        secret_version=destination.secret_version,
        status="queued",
        attempt_count=0,
        max_attempts=settings.governance_webhook_max_attempts,
        manual_retry_count=0,
        next_attempt_at=now,
    )
    destination.last_tested_at = now
    destination.last_test_status = "queued"
    destination.updated_by_id = user.id
    db.add(delivery)
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="TEST_GOVERNANCE_WEBHOOK_DESTINATION",
        entity_type="governance_webhook_destination",
        entity_id=destination.id,
        new_values={"delivery_id": str(delivery.id), "content_free": True},
        details="Synthetic content-free Phase 12I test delivery queued by an authorized admin.",
    )
    db.commit()
    db.refresh(delivery)
    return delivery


def list_deliveries(
    db: Session,
    organization_id: UUID,
    *,
    page: int,
    page_size: int,
    destination_id: UUID | None = None,
    status: str | None = None,
) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(422, "Webhook delivery pagination must use page >= 1 and page_size 1..100")
    if status is not None and status not in DELIVERY_STATUSES:
        raise HTTPException(422, "Unsupported webhook delivery status")
    conditions = [GovernanceWebhookDelivery.organization_id == organization_id]
    if destination_id is not None:
        conditions.append(GovernanceWebhookDelivery.destination_id == destination_id)
    if status is not None:
        conditions.append(GovernanceWebhookDelivery.status == status)
    total = db.scalar(select(func.count()).select_from(GovernanceWebhookDelivery).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(GovernanceWebhookDelivery)
            .where(*conditions)
            .order_by(GovernanceWebhookDelivery.created_at.desc(), GovernanceWebhookDelivery.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "deliveries": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }


def webhook_metrics(db: Session, organization_id: UUID) -> dict:
    destinations = list_destinations(db, organization_id)
    counts = {
        status: db.scalar(
            select(func.count()).select_from(GovernanceWebhookDelivery).where(
                GovernanceWebhookDelivery.organization_id == organization_id,
                GovernanceWebhookDelivery.status == status,
            )
        ) or 0
        for status in DELIVERY_STATUSES
    }
    terminal = counts["delivered"] + counts["dead_letter"]
    return {
        "destination_count": len(destinations),
        "enabled_destination_count": sum(1 for item in destinations if item.enabled),
        "queued_count": counts["queued"],
        "attempting_count": counts["attempting"],
        "failed_count": counts["failed"],
        "delivered_count": counts["delivered"],
        "dead_letter_count": counts["dead_letter"],
        "delivery_success_bps": None if terminal == 0 else round(counts["delivered"] * 10_000 / terminal),
    }


def dashboard(db: Session, organization_id: UUID) -> dict:
    return {
        "metrics": webhook_metrics(db, organization_id),
        "destinations": list_destinations(db, organization_id),
        "recent_deliveries": list_deliveries(db, organization_id, page=1, page_size=20)["deliveries"],
        "content_free_outbound_only": True,
        "inbound_commands_enabled": False,
        "raw_claim_or_model_content_exposed": False,
    }


def claim_next_delivery(db: Session, *, worker_id: str) -> GovernanceWebhookDelivery | None:
    now = datetime.now(UTC)
    stmt = (
        select(GovernanceWebhookDelivery)
        .join(
            GovernanceWebhookDestination,
            GovernanceWebhookDestination.id == GovernanceWebhookDelivery.destination_id,
        )
        .where(
            GovernanceWebhookDelivery.status.in_(["queued", "failed"]),
            GovernanceWebhookDelivery.next_attempt_at <= now,
            GovernanceWebhookDelivery.attempt_count < GovernanceWebhookDelivery.max_attempts,
            GovernanceWebhookDestination.enabled.is_(True),
        )
        .order_by(GovernanceWebhookDelivery.next_attempt_at.asc(), GovernanceWebhookDelivery.created_at.asc())
        .limit(1)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    delivery = db.scalar(stmt)
    if delivery is None:
        return None
    delivery.status = "attempting"
    delivery.attempt_count += 1
    delivery.last_attempt_at = now
    delivery.locked_at = now
    delivery.locked_by = worker_id[:120]
    db.commit()
    db.refresh(delivery)
    return delivery


def _signature_input(timestamp: int, event_id: UUID | str, body: bytes) -> bytes:
    return f"{timestamp}.{event_id}.".encode("utf-8") + body


def signed_delivery_request(
    destination: GovernanceWebhookDestination,
    delivery: GovernanceWebhookDelivery,
    *,
    now: datetime | None = None,
) -> tuple[bytes, dict[str, str]]:
    now = now or datetime.now(UTC)
    body = _canonical_json(delivery.envelope).encode("utf-8")
    if sha256(body).hexdigest() != delivery.payload_hash:
        raise RuntimeError("delivery_payload_hash_mismatch")
    signing_secret = _secret_for_delivery(destination, delivery.secret_version, now=now)
    timestamp = int(now.timestamp())
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        _signature_input(timestamp, delivery.id, body),
        sha256,
    ).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "User-Agent": "MCRI-Governance-Webhook/1",
        "X-MCRI-Webhook-Id": str(delivery.id),
        "X-MCRI-Webhook-Idempotency-Key": str(delivery.id),
        "X-MCRI-Webhook-Timestamp": str(timestamp),
        "X-MCRI-Webhook-Signature": f"v1={signature}",
        "X-MCRI-Webhook-Secret-Version": str(delivery.secret_version),
        "X-MCRI-Webhook-Envelope-Version": delivery.envelope_version,
        "X-MCRI-Webhook-Content-Free": "true",
    }


def verify_signature(
    signing_secret: str,
    *,
    body: bytes,
    timestamp: int,
    event_id: UUID | str,
    signature_header: str,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    max_age = max_age_seconds or settings.governance_webhook_replay_window_seconds
    if abs(int(now.timestamp()) - timestamp) > max_age:
        return False
    expected = hmac.new(
        signing_secret.encode("utf-8"),
        _signature_input(timestamp, event_id, body),
        sha256,
    ).hexdigest()
    supplied = signature_header.removeprefix("v1=")
    return hmac.compare_digest(expected, supplied)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _stdlib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> int:
    _ensure_resolved_public_destination(url)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _retry_delay_seconds(delivery: GovernanceWebhookDelivery) -> int:
    exponent = max(0, delivery.attempt_count - 1)
    base = min(3600, 10 * (2**exponent))
    jitter = int(sha256(str(delivery.id).encode()).hexdigest()[:2], 16) % 7
    return base + jitter


def _mark_failure(
    db: Session,
    delivery: GovernanceWebhookDelivery,
    *,
    error_code: str,
    http_status: int | None = None,
) -> None:
    now = datetime.now(UTC)
    delivery.last_http_status = http_status
    delivery.last_error_code = error_code[:80]
    delivery.locked_at = None
    delivery.locked_by = None
    if delivery.attempt_count >= delivery.max_attempts:
        delivery.status = "dead_letter"
        delivery.next_attempt_at = now
    else:
        delivery.status = "failed"
        delivery.next_attempt_at = now + timedelta(seconds=_retry_delay_seconds(delivery))
    destination = db.get(GovernanceWebhookDestination, delivery.destination_id)
    if destination is not None and delivery.source_workflow_type == "test":
        destination.last_test_status = delivery.status
        destination.last_tested_at = now
    db.commit()


def process_delivery(
    db: Session,
    *,
    delivery: GovernanceWebhookDelivery,
    transport: Callable[[str, dict[str, str], bytes, float], int] | None = None,
) -> None:
    destination = db.scalar(
        select(GovernanceWebhookDestination).where(
            GovernanceWebhookDestination.id == delivery.destination_id,
            GovernanceWebhookDestination.organization_id == delivery.organization_id,
        )
    )
    if destination is None:
        delivery.status = "dead_letter"
        delivery.last_error_code = "destination_missing"
        delivery.locked_at = None
        delivery.locked_by = None
        db.commit()
        return
    if not destination.enabled:
        _mark_failure(db, delivery, error_code="destination_disabled")
        return
    try:
        body, headers = signed_delivery_request(destination, delivery)
    except SigningKeyUnavailable:
        delivery.status = "dead_letter"
        delivery.last_error_code = "signing_key_version_unavailable"
        delivery.locked_at = None
        delivery.locked_by = None
        db.commit()
        return
    except RuntimeError:
        delivery.status = "dead_letter"
        delivery.last_error_code = "payload_integrity_failure"
        delivery.locked_at = None
        delivery.locked_by = None
        db.commit()
        return
    sender = transport or _stdlib_transport
    try:
        status = sender(
            destination.endpoint_url,
            headers,
            body,
            settings.governance_webhook_timeout_seconds,
        )
    except DestinationSecurityError:
        delivery.status = "dead_letter"
        delivery.last_error_code = "ssrf_destination_blocked"
        delivery.locked_at = None
        delivery.locked_by = None
        db.commit()
        return
    except (TimeoutError, socket.timeout):
        _mark_failure(db, delivery, error_code="delivery_timeout")
        return
    except (urllib.error.URLError, OSError):
        _mark_failure(db, delivery, error_code="network_error")
        return
    except Exception:  # never persist arbitrary transport exception text
        _mark_failure(db, delivery, error_code="transport_error")
        return
    if 200 <= status < 300:
        now = datetime.now(UTC)
        delivery.status = "delivered"
        delivery.delivered_at = now
        delivery.last_http_status = status
        delivery.last_error_code = None
        delivery.locked_at = None
        delivery.locked_by = None
        destination.last_test_status = "delivered" if delivery.source_workflow_type == "test" else destination.last_test_status
        if delivery.source_workflow_type == "test":
            destination.last_tested_at = now
        db.commit()
        return
    if 400 <= status < 500:
        code = "http_429" if status == 429 else "http_4xx"
    elif 500 <= status < 600:
        code = "http_5xx"
    elif 300 <= status < 400:
        code = "redirect_blocked"
    else:
        code = "unexpected_http_status"
    _mark_failure(db, delivery, error_code=code, http_status=status)


def manual_retry_delivery(
    db: Session,
    user: User,
    delivery_id: UUID,
) -> GovernanceWebhookDelivery:
    delivery = db.scalar(
        select(GovernanceWebhookDelivery).where(
            GovernanceWebhookDelivery.id == delivery_id,
            GovernanceWebhookDelivery.organization_id == user.organization_id,
        )
    )
    if delivery is None:
        raise HTTPException(404, "Governance webhook delivery not found")
    if delivery.status not in {"failed", "dead_letter"}:
        raise HTTPException(409, "Only failed or dead-letter webhook deliveries can be retried")
    destination = get_destination(db, user.organization_id, delivery.destination_id)
    if not destination.enabled:
        raise HTTPException(409, "Enable the webhook destination before retrying delivery")
    delivery.status = "queued"
    delivery.attempt_count = 0
    delivery.manual_retry_count += 1
    delivery.next_attempt_at = datetime.now(UTC)
    delivery.locked_at = None
    delivery.locked_by = None
    delivery.last_error_code = None
    delivery.last_http_status = None
    delivery.delivered_at = None
    delivery.secret_version = destination.secret_version
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="RETRY_GOVERNANCE_WEBHOOK_DELIVERY",
        entity_type="governance_webhook_delivery",
        entity_id=delivery.id,
        new_values={
            "destination_id": str(destination.id),
            "manual_retry_count": delivery.manual_retry_count,
            "secret_version": delivery.secret_version,
            "content_free": True,
        },
        details="Explicit human retry queued for a content-free Phase 12I delivery.",
    )
    db.commit()
    db.refresh(delivery)
    return delivery
