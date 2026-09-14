from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.credential_reference_health_models import (
    ExternalDocumentSourceCredentialReferenceHealthQualification,
)
from app.modules.external_document_sources.credential_reference_health_service import (
    get_external_document_source_credential_reference_health_qualification,
)
from app.modules.external_document_sources.provider_client_activation_authorization_models import (
    ExternalDocumentSourceProviderClientActivationAuthorization,
    ExternalDocumentSourceProviderClientActivationAuthorizationReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)

_REVIEW_TTL = timedelta(minutes=10)
_AUTHORIZATION_TTL = timedelta(minutes=10)
_FALSE_SAFETY_FIELDS = (
    "credential_reference_resolution_performed",
    "credential_stored",
    "oauth_authorization_code_stored",
    "oauth_token_exchanged",
    "access_token_stored",
    "refresh_token_stored",
    "client_secret_stored",
    "private_key_stored",
    "provider_network_performed",
    "remote_list_performed",
    "remote_read_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "subscription_created",
    "checkpoint_created",
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


def _scope_hash(*, qualification: ExternalDocumentSourceCredentialReferenceHealthQualification, request_key: str) -> str:
    return _canonical_hash(
        {
            "organization_id": str(qualification.organization_id),
            "profile_id": str(qualification.profile_id),
            "provider_kind": qualification.provider_kind,
            "profile_hash": qualification.profile_hash,
            "credential_reference_binding_id": str(qualification.credential_reference_binding_id),
            "binding_scope_hash": qualification.binding_scope_hash,
            "binding_request_hash": qualification.binding_request_hash,
            "binding_approval_hash": qualification.binding_approval_hash,
            "locator_hash": qualification.locator_hash,
            "reference_backend": qualification.reference_backend,
            "resolver_kind": qualification.resolver_kind,
            "health_qualification_id": str(qualification.id),
            "health_scope_hash": qualification.scope_hash,
            "health_request_hash": qualification.request_hash,
            "health_result_hash": qualification.result_hash,
            "health_result_status": qualification.result_status,
            "request_key": request_key,
            "execution_limit": 1,
        }
    )


def _request_hash(row: ExternalDocumentSourceProviderClientActivationAuthorization) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(row.id),
            "scope_hash": row.scope_hash,
            "requested_by_id": str(row.requested_by_id),
            "request_reason": row.request_reason,
            "requested_at": _iso(row.requested_at),
            "review_expires_at": _iso(row.review_expires_at),
            "execution_limit": row.execution_limit,
            "credential_reference_stored": True,
            "provider_client_activation_authorized": False,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _authorization_hash(row: ExternalDocumentSourceProviderClientActivationAuthorization) -> str:
    if row.approved_by_id is None or row.approved_at is None or row.approval_reason is None or row.authorization_expires_at is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization decision is incomplete")
    return _canonical_hash(
        {
            "authorization_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "approved_by_id": str(row.approved_by_id),
            "approved_at": _iso(row.approved_at),
            "approval_reason": row.approval_reason,
            "authorization_expires_at": _iso(row.authorization_expires_at),
            "execution_limit": row.execution_limit,
            "credential_reference_stored": True,
            "provider_client_activation_authorized": True,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _terminal_hash(row: ExternalDocumentSourceProviderClientActivationAuthorization) -> str:
    if row.terminal_at is None or row.terminal_reason is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation terminal decision is incomplete")
    return _canonical_hash(
        {
            "authorization_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "authorization_hash": row.authorization_hash,
            "status": row.status,
            "terminal_by_id": str(row.terminal_by_id) if row.terminal_by_id else None,
            "terminal_at": _iso(row.terminal_at),
            "terminal_reason": row.terminal_reason,
            "credential_reference_stored": True,
            "provider_client_activation_authorized": False,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceProviderClientActivationAuthorizationReceipt) -> str:
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
            "credential_reference_stored": True,
            "provider_client_activation_authorized": receipt.provider_client_activation_authorized,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _get_authorization(db: Session, *, organization_id: UUID, profile_id: UUID, authorization_id: UUID):
    row = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationAuthorization).where(
            ExternalDocumentSourceProviderClientActivationAuthorization.id == authorization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Provider-client activation authorization not found")
    return row


def _receipts(db: Session, row: ExternalDocumentSourceProviderClientActivationAuthorization):
    return list(
        db.scalars(
            select(ExternalDocumentSourceProviderClientActivationAuthorizationReceipt)
            .where(
                ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.organization_id == row.organization_id,
                ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.authorization_id == row.id,
            )
            .order_by(ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.sequence_number.asc())
        ).all()
    )


def _lineage(db: Session, row: ExternalDocumentSourceProviderClientActivationAuthorization):
    qualification = get_external_document_source_credential_reference_health_qualification(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        qualification_id=row.health_qualification_id,
    )
    if qualification.result_status != "resolvable" or qualification.failure_code is not None:
        raise ExternalDocumentSourceConflictError("Provider-client activation requires a resolvable Phase F qualification")
    if (
        row.credential_reference_binding_id != qualification.credential_reference_binding_id
        or row.provider_kind != qualification.provider_kind
        or row.profile_hash != qualification.profile_hash
        or row.binding_scope_hash != qualification.binding_scope_hash
        or row.binding_request_hash != qualification.binding_request_hash
        or row.binding_approval_hash != qualification.binding_approval_hash
        or row.locator_hash != qualification.locator_hash
        or row.reference_backend != qualification.reference_backend
        or row.resolver_kind != qualification.resolver_kind
        or row.health_scope_hash != qualification.scope_hash
        or row.health_request_hash != qualification.request_hash
        or row.health_result_hash != qualification.result_hash
        or row.health_result_status != qualification.result_status
    ):
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization upstream lineage drifted")
    return qualification


def _expected_events(row: ExternalDocumentSourceProviderClientActivationAuthorization) -> list[str]:
    if row.status == "pending_second_approval":
        return ["requested"]
    if row.status == "authorized":
        return ["requested", "authorized"]
    if row.status == "rejected":
        return ["requested", "rejected"]
    if row.status == "expired":
        return ["requested", "authorized", "expired"] if row.authorization_hash else ["requested", "expired"]
    raise ExternalDocumentSourceConflictError("Provider-client activation authorization status is invalid")


def _expected_receipt_facts(row: ExternalDocumentSourceProviderClientActivationAuthorization, event_type: str):
    if event_type == "requested":
        return row.requested_by_id, row.requested_at, row.request_reason, "pending_second_approval", row.request_hash, False
    if event_type == "authorized":
        return row.approved_by_id, row.approved_at, row.approval_reason, "authorized", row.authorization_hash, True
    if event_type == "rejected":
        return row.terminal_by_id, row.terminal_at, row.terminal_reason, "rejected", row.terminal_hash, False
    if event_type == "expired":
        return None, row.terminal_at, row.terminal_reason, "expired", row.terminal_hash, False
    raise ExternalDocumentSourceConflictError("Provider-client activation receipt event is invalid")


def _ensure_integrity(db: Session, row: ExternalDocumentSourceProviderClientActivationAuthorization) -> None:
    qualification = _lineage(db, row)
    expected_scope = _scope_hash(qualification=qualification, request_key=row.request_key)
    if row.scope_hash != expected_scope or row.request_hash != _request_hash(row):
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization request integrity failed")
    if _aware(row.review_expires_at) != _aware(row.requested_at) + _REVIEW_TTL:
        raise ExternalDocumentSourceConflictError("Provider-client activation review TTL drifted")
    if row.execution_limit != 1:
        raise ExternalDocumentSourceConflictError("Provider-client activation execution boundary drifted")
    if not row.credential_reference_stored or any(bool(getattr(row, field)) for field in _FALSE_SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization safety boundary drifted")
    if row.provider_client_activation_authorized != (row.status == "authorized"):
        raise ExternalDocumentSourceConflictError("Provider-client activation authority mapping drifted")
    if row.authorization_hash is not None:
        if row.authorization_hash != _authorization_hash(row):
            raise ExternalDocumentSourceConflictError("Provider-client activation authorization decision integrity failed")
        if row.approved_at is None or row.authorization_expires_at is None:
            raise ExternalDocumentSourceConflictError("Provider-client activation authorization timing is incomplete")
        if _aware(row.authorization_expires_at) != _aware(row.approved_at) + _AUTHORIZATION_TTL:
            raise ExternalDocumentSourceConflictError("Provider-client activation authorization TTL drifted")
    if row.status in {"authorized", "expired"} and row.approved_by_id is not None and row.requested_by_id == row.approved_by_id:
        raise ExternalDocumentSourceConflictError("Provider-client activation four-eyes boundary drifted")
    if row.terminal_hash is not None and row.terminal_hash != _terminal_hash(row):
        raise ExternalDocumentSourceConflictError("Provider-client activation terminal integrity failed")

    receipts = _receipts(db, row)
    events = _expected_events(row)
    if len(receipts) != len(events) or [receipt.event_type for receipt in receipts] != events:
        raise ExternalDocumentSourceConflictError("Provider-client activation receipt lifecycle is incomplete")
    prior: str | None = None
    for sequence, receipt in enumerate(receipts, start=1):
        if receipt.sequence_number != sequence or receipt.prior_receipt_hash != prior or receipt.scope_hash != row.scope_hash:
            raise ExternalDocumentSourceConflictError("Provider-client activation receipt chain linkage failed")
        if not receipt.credential_reference_stored or any(bool(getattr(receipt, field)) for field in _FALSE_SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("Provider-client activation receipt safety boundary drifted")
        expected_actor, expected_time, expected_reason, expected_status, expected_decision, expected_authorized = _expected_receipt_facts(row, receipt.event_type)
        if expected_time is None or expected_reason is None or expected_decision is None:
            raise ExternalDocumentSourceConflictError("Provider-client activation receipt facts are incomplete")
        if (
            receipt.actor_id != expected_actor
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != expected_reason
            or receipt.status_after != expected_status
            or receipt.decision_hash != expected_decision
            or receipt.provider_client_activation_authorized != expected_authorized
        ):
            raise ExternalDocumentSourceConflictError("Provider-client activation receipt facts drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Provider-client activation receipt integrity failed")
        prior = receipt.receipt_hash


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceProviderClientActivationAuthorization,
    event_type: str,
    actor_id: UUID | None,
    occurred_at: datetime,
    reason: str,
    decision_hash: str,
    authorized: bool,
) -> None:
    receipts = _receipts(db, row)
    receipt = ExternalDocumentSourceProviderClientActivationAuthorizationReceipt(
        organization_id=row.organization_id,
        authorization_id=row.id,
        sequence_number=len(receipts) + 1,
        event_type=event_type,
        status_after=row.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=receipts[-1].receipt_hash if receipts else None,
        credential_reference_stored=True,
        provider_client_activation_authorized=authorized,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _terminalize_expired(db: Session, row: ExternalDocumentSourceProviderClientActivationAuthorization, *, current: datetime, reason: str) -> None:
    row.status = "expired"
    row.provider_client_activation_authorized = False
    row.terminal_by_id = None
    row.terminal_at = current
    row.terminal_reason = reason
    row.terminal_hash = _terminal_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="expired",
        actor_id=None,
        occurred_at=current,
        reason=reason,
        decision_hash=row.terminal_hash,
        authorized=False,
    )
    db.flush()


def _expire_if_needed(db: Session, row: ExternalDocumentSourceProviderClientActivationAuthorization, *, now: datetime) -> bool:
    current = _aware(now)
    if row.status not in {"pending_second_approval", "authorized"}:
        return False
    if row.status == "pending_second_approval" and current >= _aware(row.review_expires_at):
        _terminalize_expired(db, row, current=current, reason="Second-approval review window expired.")
        return True
    if row.status == "authorized" and row.authorization_expires_at is not None and current >= _aware(row.authorization_expires_at):
        _terminalize_expired(db, row, current=current, reason="Bounded provider-client activation authorization expired unused.")
        return True
    return False


def request_external_document_source_provider_client_activation_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    health_qualification_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    locked = db.scalar(
        select(ExternalDocumentSourceCredentialReferenceHealthQualification)
        .where(
            ExternalDocumentSourceCredentialReferenceHealthQualification.id == health_qualification_id,
            ExternalDocumentSourceCredentialReferenceHealthQualification.organization_id == organization_id,
            ExternalDocumentSourceCredentialReferenceHealthQualification.profile_id == profile_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise ExternalDocumentSourceNotFoundError("Credential reference health qualification not found")
    qualification = get_external_document_source_credential_reference_health_qualification(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        qualification_id=health_qualification_id,
    )
    if qualification.result_status != "resolvable" or qualification.failure_code is not None:
        raise ExternalDocumentSourceConflictError("Provider-client activation requires a resolvable Phase F qualification")

    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    scope_hash = _scope_hash(qualification=qualification, request_key=normalized_key)

    existing = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationAuthorization).where(
            ExternalDocumentSourceProviderClientActivationAuthorization.health_qualification_id == health_qualification_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        changed = _expire_if_needed(db, existing, now=now or _utc_now())
        if (
            existing.request_key != normalized_key
            or existing.requested_by_id != requested_by_id
            or existing.request_reason != normalized_reason
            or existing.scope_hash != scope_hash
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for provider-client activation authorization")
        _ensure_integrity(db, existing)
        return existing, "expired" if changed else "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationAuthorization).where(
            ExternalDocumentSourceProviderClientActivationAuthorization.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.profile_id == profile_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for provider-client activation request_key")

    requested_at = _aware(now or _utc_now())
    row = ExternalDocumentSourceProviderClientActivationAuthorization(
        organization_id=organization_id,
        profile_id=profile_id,
        health_qualification_id=qualification.id,
        credential_reference_binding_id=qualification.credential_reference_binding_id,
        provider_kind=qualification.provider_kind,
        profile_hash=qualification.profile_hash,
        binding_scope_hash=qualification.binding_scope_hash,
        binding_request_hash=qualification.binding_request_hash,
        binding_approval_hash=qualification.binding_approval_hash,
        locator_hash=qualification.locator_hash,
        reference_backend=qualification.reference_backend,
        resolver_kind=qualification.resolver_kind,
        health_scope_hash=qualification.scope_hash,
        health_request_hash=qualification.request_hash,
        health_result_hash=qualification.result_hash,
        health_result_status=qualification.result_status,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        execution_limit=1,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        review_expires_at=requested_at + _REVIEW_TTL,
        credential_reference_stored=True,
        provider_client_activation_authorized=False,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    db.add(row)
    db.flush()
    row.request_hash = _request_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=requested_at,
        reason=normalized_reason,
        decision_hash=row.request_hash,
        authorized=False,
    )
    db.flush()
    _ensure_integrity(db, row)
    return row, "requested"


def approve_external_document_source_provider_client_activation_authorization(
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
    row = _get_authorization(db, organization_id=organization_id, profile_id=profile_id, authorization_id=authorization_id)
    _ensure_integrity(db, row)
    current = _aware(now or _utc_now())
    if _expire_if_needed(db, row, now=current):
        _ensure_integrity(db, row)
        return row, "expired"
    if row.status == "authorized":
        if row.approved_by_id == approved_by_id and row.approval_reason == normalized_reason:
            return row, "unchanged"
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization is already approved")
    if row.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization is not pending approval")
    if row.requested_by_id == approved_by_id:
        raise ExternalDocumentSourceConflictError("Independent second approval is required")

    row.status = "authorized"
    row.approved_by_id = approved_by_id
    row.approved_at = current
    row.approval_reason = normalized_reason
    row.authorization_expires_at = current + _AUTHORIZATION_TTL
    row.provider_client_activation_authorized = True
    row.authorization_hash = _authorization_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="authorized",
        actor_id=approved_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=row.authorization_hash,
        authorized=True,
    )
    db.flush()
    _ensure_integrity(db, row)
    return row, "authorized"


def reject_external_document_source_provider_client_activation_authorization(
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
    row = _get_authorization(db, organization_id=organization_id, profile_id=profile_id, authorization_id=authorization_id)
    _ensure_integrity(db, row)
    current = _aware(now or _utc_now())
    if _expire_if_needed(db, row, now=current):
        _ensure_integrity(db, row)
        return row, "expired"
    if row.status == "rejected":
        if row.terminal_by_id == rejected_by_id and row.terminal_reason == normalized_reason:
            return row, "unchanged"
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization is already rejected")
    if row.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization is not pending rejection")

    row.status = "rejected"
    row.terminal_by_id = rejected_by_id
    row.terminal_at = current
    row.terminal_reason = normalized_reason
    row.provider_client_activation_authorized = False
    row.terminal_hash = _terminal_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="rejected",
        actor_id=rejected_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=row.terminal_hash,
        authorized=False,
    )
    db.flush()
    _ensure_integrity(db, row)
    return row, "rejected"


def get_external_document_source_provider_client_activation_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
):
    row = _get_authorization(db, organization_id=organization_id, profile_id=profile_id, authorization_id=authorization_id)
    _ensure_integrity(db, row)
    changed = _expire_if_needed(db, row, now=_aware(now or _utc_now()))
    _ensure_integrity(db, row)
    return row, "expired" if changed else "unchanged"


def list_external_document_source_provider_client_activation_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
):
    row, outcome = get_external_document_source_provider_client_activation_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
        now=now,
    )
    return _receipts(db, row), outcome
