from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.provider_client_activation_authorization_models import (
    ExternalDocumentSourceProviderClientActivationAuthorization,
)
from app.modules.external_document_sources.provider_client_activation_authorization_service import (
    _ensure_integrity as _ensure_activation_authorization_integrity,
    _terminalize_expired,
)
from app.modules.external_document_sources.provider_client_activation_execution_models import (
    ExternalDocumentSourceProviderClientActivationExecution,
    ExternalDocumentSourceProviderClientActivationExecutionReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)

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
    "provider_client_activation_authorized",
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


def _scope_hash(*, authorization: ExternalDocumentSourceProviderClientActivationAuthorization, request_key: str) -> str:
    if authorization.authorization_hash is None or authorization.authorization_expires_at is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization approval facts are incomplete")
    return _canonical_hash(
        {
            "organization_id": str(authorization.organization_id),
            "profile_id": str(authorization.profile_id),
            "authorization_id": str(authorization.id),
            "health_qualification_id": str(authorization.health_qualification_id),
            "credential_reference_binding_id": str(authorization.credential_reference_binding_id),
            "provider_kind": authorization.provider_kind,
            "profile_hash": authorization.profile_hash,
            "binding_scope_hash": authorization.binding_scope_hash,
            "binding_request_hash": authorization.binding_request_hash,
            "binding_approval_hash": authorization.binding_approval_hash,
            "locator_hash": authorization.locator_hash,
            "reference_backend": authorization.reference_backend,
            "resolver_kind": authorization.resolver_kind,
            "health_scope_hash": authorization.health_scope_hash,
            "health_request_hash": authorization.health_request_hash,
            "health_result_hash": authorization.health_result_hash,
            "health_result_status": authorization.health_result_status,
            "activation_authorization_scope_hash": authorization.scope_hash,
            "activation_authorization_request_hash": authorization.request_hash,
            "activation_authorization_hash": authorization.authorization_hash,
            "activation_authorization_expires_at": _iso(authorization.authorization_expires_at),
            "request_key": request_key,
            "execution_limit": 1,
        }
    )


def _request_hash(execution: ExternalDocumentSourceProviderClientActivationExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            "credential_reference_stored": True,
            "activation_authorization_consumed": False,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _completion_hash(execution: ExternalDocumentSourceProviderClientActivationExecution) -> str:
    if execution.authorization_terminal_hash is None or execution.completed_at is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation execution completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "authorization_terminal_hash": execution.authorization_terminal_hash,
            "completed_at": _iso(execution.completed_at),
            "credential_reference_stored": True,
            "activation_authorization_consumed": True,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceProviderClientActivationExecutionReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "execution_id": str(receipt.execution_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "actor_id": str(receipt.actor_id),
            "occurred_at": _iso(receipt.occurred_at),
            "reason": receipt.reason,
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            "prior_receipt_hash": receipt.prior_receipt_hash,
            "credential_reference_stored": True,
            "activation_authorization_consumed": receipt.activation_authorization_consumed,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _consumption_reason(execution_id: UUID) -> str:
    return f"Phase 17.5-H activation execution {execution_id} consumed this bounded provider-client activation authorization."


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceProviderClientActivationExecution:
    row = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationExecution).where(
            ExternalDocumentSourceProviderClientActivationExecution.id == execution_id,
            ExternalDocumentSourceProviderClientActivationExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Provider-client activation execution not found")
    return row


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceProviderClientActivationExecution,
) -> list[ExternalDocumentSourceProviderClientActivationExecutionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceProviderClientActivationExecutionReceipt)
            .where(
                ExternalDocumentSourceProviderClientActivationExecutionReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceProviderClientActivationExecutionReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceProviderClientActivationExecutionReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceProviderClientActivationExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    decision_hash: str,
    consumed: bool,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceProviderClientActivationExecutionReceipt(
        organization_id=execution.organization_id,
        execution_id=execution.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=execution.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        scope_hash=execution.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        credential_reference_stored=True,
        activation_authorization_consumed=consumed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _authorization_for_execution(
    db: Session,
    execution: ExternalDocumentSourceProviderClientActivationExecution,
) -> ExternalDocumentSourceProviderClientActivationAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationAuthorization).where(
            ExternalDocumentSourceProviderClientActivationAuthorization.id == execution.authorization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.organization_id == execution.organization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.profile_id == execution.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation execution authorization lineage is missing")
    return authorization


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceProviderClientActivationExecution) -> None:
    if execution.status != "completed" or not execution.activation_authorization_consumed:
        raise ExternalDocumentSourceConflictError("Provider-client activation execution lifecycle is incomplete")
    if not execution.credential_reference_stored or any(bool(getattr(execution, field)) for field in _FALSE_SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("Provider-client activation execution safety boundary drifted")

    authorization = _authorization_for_execution(db, execution)
    _ensure_activation_authorization_integrity(db, authorization)
    if authorization.status != "expired" or authorization.provider_client_activation_authorized:
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization was not terminalized by execution")
    if authorization.authorization_hash is None or authorization.authorization_expires_at is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization approval facts are incomplete")
    if authorization.terminal_hash is None or authorization.terminal_at is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization terminal facts are incomplete")
    if authorization.terminal_reason != _consumption_reason(execution.id):
        raise ExternalDocumentSourceConflictError("Provider-client activation execution consumption lineage drifted")
    if _aware(authorization.terminal_at) != _aware(execution.completed_at):
        raise ExternalDocumentSourceConflictError("Provider-client activation execution completion timing drifted")
    if execution.completed_at is None or _aware(execution.completed_at) >= _aware(authorization.authorization_expires_at):
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization was not consumed before expiry")

    expected_bindings = (
        execution.health_qualification_id == authorization.health_qualification_id,
        execution.credential_reference_binding_id == authorization.credential_reference_binding_id,
        execution.provider_kind == authorization.provider_kind,
        execution.profile_hash == authorization.profile_hash,
        execution.binding_scope_hash == authorization.binding_scope_hash,
        execution.binding_request_hash == authorization.binding_request_hash,
        execution.binding_approval_hash == authorization.binding_approval_hash,
        execution.locator_hash == authorization.locator_hash,
        execution.reference_backend == authorization.reference_backend,
        execution.resolver_kind == authorization.resolver_kind,
        execution.health_scope_hash == authorization.health_scope_hash,
        execution.health_request_hash == authorization.health_request_hash,
        execution.health_result_hash == authorization.health_result_hash,
        execution.health_result_status == authorization.health_result_status,
        execution.activation_authorization_scope_hash == authorization.scope_hash,
        execution.activation_authorization_request_hash == authorization.request_hash,
        execution.activation_authorization_hash == authorization.authorization_hash,
        _aware(execution.activation_authorization_expires_at) == _aware(authorization.authorization_expires_at),
        execution.authorization_terminal_hash == authorization.terminal_hash,
        execution.execution_limit == authorization.execution_limit == 1,
    )
    if not all(expected_bindings):
        raise ExternalDocumentSourceConflictError("Provider-client activation execution lineage drifted")

    expected_scope = _scope_hash(authorization=authorization, request_key=execution.request_key)
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Provider-client activation execution request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Provider-client activation execution completion integrity failed")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt lifecycle is incomplete")
    prior: str | None = None
    for sequence, receipt in enumerate(rows, start=1):
        if receipt.sequence_number != sequence or receipt.prior_receipt_hash != prior:
            raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt chain linkage failed")
        if receipt.scope_hash != execution.scope_hash or receipt.actor_id != execution.requested_by_id:
            raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt scope or actor drifted")
        if not receipt.credential_reference_stored or any(bool(getattr(receipt, field)) for field in _FALSE_SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt safety boundary drifted")
        if receipt.event_type == "requested":
            expected_status = "requested"
            expected_time = execution.requested_at
            expected_decision = execution.request_hash
            expected_consumed = False
        else:
            expected_status = "completed"
            expected_time = execution.completed_at
            expected_decision = execution.completion_hash
            expected_consumed = True
        if expected_time is None or expected_decision is None:
            raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt facts are incomplete")
        if (
            receipt.status_after != expected_status
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != execution.request_reason
            or receipt.decision_hash != expected_decision
            or receipt.activation_authorization_consumed != expected_consumed
        ):
            raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt facts drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Provider-client activation execution receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_provider_client_activation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationExecution).where(
            ExternalDocumentSourceProviderClientActivationExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationExecution.profile_id == profile_id,
            ExternalDocumentSourceProviderClientActivationExecution.authorization_id == authorization_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for consumed provider-client activation authorization")
        return existing, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationExecution).where(
            ExternalDocumentSourceProviderClientActivationExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationExecution.profile_id == profile_id,
            ExternalDocumentSourceProviderClientActivationExecution.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for provider-client activation execution request_key")

    authorization = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationAuthorization)
        .where(
            ExternalDocumentSourceProviderClientActivationAuthorization.id == authorization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationAuthorization.profile_id == profile_id,
        )
        .with_for_update()
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError("Provider-client activation authorization not found")

    # A concurrent executor may have completed while this transaction waited for
    # the authorization row lock. Re-check after acquiring the lock.
    existing = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationExecution).where(
            ExternalDocumentSourceProviderClientActivationExecution.authorization_id == authorization_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for consumed provider-client activation authorization")
        return existing, "unchanged"

    _ensure_activation_authorization_integrity(db, authorization)
    current = _aware(now or _utc_now())
    if (
        authorization.status != "authorized"
        or not authorization.provider_client_activation_authorized
        or authorization.authorization_hash is None
        or authorization.authorization_expires_at is None
        or authorization.execution_limit != 1
    ):
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization is not consumable")
    if current >= _aware(authorization.authorization_expires_at):
        _terminalize_expired(
            db,
            authorization,
            current=current,
            reason="Bounded provider-client activation authorization expired unused.",
        )
        _ensure_activation_authorization_integrity(db, authorization)
        return None, "expired"

    scope_hash = _scope_hash(authorization=authorization, request_key=normalized_key)
    execution = ExternalDocumentSourceProviderClientActivationExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization.id,
        health_qualification_id=authorization.health_qualification_id,
        credential_reference_binding_id=authorization.credential_reference_binding_id,
        provider_kind=authorization.provider_kind,
        profile_hash=authorization.profile_hash,
        binding_scope_hash=authorization.binding_scope_hash,
        binding_request_hash=authorization.binding_request_hash,
        binding_approval_hash=authorization.binding_approval_hash,
        locator_hash=authorization.locator_hash,
        reference_backend=authorization.reference_backend,
        resolver_kind=authorization.resolver_kind,
        health_scope_hash=authorization.health_scope_hash,
        health_request_hash=authorization.health_request_hash,
        health_result_hash=authorization.health_result_hash,
        health_result_status=authorization.health_result_status,
        activation_authorization_scope_hash=authorization.scope_hash,
        activation_authorization_request_hash=authorization.request_hash,
        activation_authorization_hash=authorization.authorization_hash,
        activation_authorization_expires_at=authorization.authorization_expires_at,
        execution_limit=1,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        credential_reference_stored=True,
        activation_authorization_consumed=False,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    db.add(execution)
    db.flush()
    execution.request_hash = _request_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=execution.request_hash,
        consumed=False,
    )

    _terminalize_expired(
        db,
        authorization,
        current=current,
        reason=_consumption_reason(execution.id),
    )
    if authorization.terminal_hash is None:
        raise ExternalDocumentSourceConflictError("Provider-client activation authorization terminal hash is missing")

    execution.status = "completed"
    execution.authorization_terminal_hash = authorization.terminal_hash
    execution.completed_at = current
    execution.activation_authorization_consumed = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=execution.completion_hash,
        consumed=True,
    )
    db.flush()
    _ensure_activation_authorization_integrity(db, authorization)
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_provider_client_activation_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = _get_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_provider_client_activation_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_provider_client_activation_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
