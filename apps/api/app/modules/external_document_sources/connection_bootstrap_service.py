import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.connection_authorization_models import (
    ExternalDocumentSourceConnectionAuthorization,
)
from app.modules.external_document_sources.connection_authorization_service import (
    _ensure_integrity as _ensure_authorization_integrity,
    _terminalize_expired,
    get_external_document_source_connection_authorization,
)
from app.modules.external_document_sources.connection_bootstrap_models import (
    ExternalDocumentSourceConnectionBootstrapExecution,
    ExternalDocumentSourceConnectionBootstrapExecutionReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)


_SAFETY_FIELDS = (
    "credential_stored",
    "credential_reference_stored",
    "oauth_token_exchanged",
    "provider_network_performed",
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


def _scope_hash(*, authorization: ExternalDocumentSourceConnectionAuthorization, request_key: str) -> str:
    if authorization.authorization_hash is None:
        raise ExternalDocumentSourceConflictError("External provider connection authorization is not approved")
    return _canonical_hash(
        {
            "organization_id": str(authorization.organization_id),
            "profile_id": str(authorization.profile_id),
            "discovery_run_id": str(authorization.discovery_run_id),
            "authorization_id": str(authorization.id),
            "provider_kind": authorization.provider_kind,
            "profile_hash": authorization.profile_hash,
            "discovery_scope_hash": authorization.discovery_scope_hash,
            "discovery_manifest_hash": authorization.discovery_manifest_hash,
            "discovery_run_hash": authorization.discovery_run_hash,
            "authorization_scope_hash": authorization.scope_hash,
            "authorization_hash": authorization.authorization_hash,
            "request_key": request_key,
            "execution_limit": 1,
        }
    )


def _request_hash(execution: ExternalDocumentSourceConnectionBootstrapExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            "authorization_consumed": False,
        }
    )


def _completion_hash(execution: ExternalDocumentSourceConnectionBootstrapExecution) -> str:
    if execution.authorization_terminal_hash is None or execution.completed_at is None:
        raise ExternalDocumentSourceConflictError("External provider bootstrap completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "authorization_terminal_hash": execution.authorization_terminal_hash,
            "completed_at": _iso(execution.completed_at),
            "authorization_consumed": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceConnectionBootstrapExecutionReceipt) -> str:
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
            "authorization_consumed": receipt.authorization_consumed,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _consumption_reason(execution_id: UUID) -> str:
    return f"Phase 17.5-D bootstrap execution {execution_id} consumed this bounded authorization."


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceConnectionBootstrapExecution:
    row = db.scalar(
        select(ExternalDocumentSourceConnectionBootstrapExecution).where(
            ExternalDocumentSourceConnectionBootstrapExecution.id == execution_id,
            ExternalDocumentSourceConnectionBootstrapExecution.organization_id == organization_id,
            ExternalDocumentSourceConnectionBootstrapExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("External provider bootstrap execution not found")
    return row


def _receipts(
    db: Session, execution: ExternalDocumentSourceConnectionBootstrapExecution
) -> list[ExternalDocumentSourceConnectionBootstrapExecutionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceConnectionBootstrapExecutionReceipt)
            .where(
                ExternalDocumentSourceConnectionBootstrapExecutionReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceConnectionBootstrapExecutionReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceConnectionBootstrapExecutionReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceConnectionBootstrapExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    decision_hash: str,
    authorization_consumed: bool,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceConnectionBootstrapExecutionReceipt(
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
        authorization_consumed=authorization_consumed,
        **{field: False for field in _SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceConnectionBootstrapExecution) -> None:
    if execution.status != "completed" or not execution.authorization_consumed:
        raise ExternalDocumentSourceConflictError("External provider bootstrap execution lifecycle is incomplete")
    if any(bool(getattr(execution, field)) for field in _SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("External provider bootstrap execution safety boundary drifted")

    authorization, _ = get_external_document_source_connection_authorization(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        authorization_id=execution.authorization_id,
        now=execution.completed_at,
    )
    _ensure_authorization_integrity(db, authorization)
    if authorization.status != "expired" or authorization.live_connection_authorized:
        raise ExternalDocumentSourceConflictError("External provider bootstrap authorization was not terminalized")
    if authorization.authorization_hash is None or authorization.terminal_hash is None or authorization.terminal_at is None:
        raise ExternalDocumentSourceConflictError("External provider bootstrap authorization terminal facts are incomplete")
    if authorization.terminal_reason != _consumption_reason(execution.id):
        raise ExternalDocumentSourceConflictError("External provider bootstrap authorization consumption lineage drifted")
    if _aware(authorization.terminal_at) != _aware(execution.completed_at):
        raise ExternalDocumentSourceConflictError("External provider bootstrap completion timing drifted")

    expected_bindings = (
        execution.discovery_run_id == authorization.discovery_run_id,
        execution.provider_kind == authorization.provider_kind,
        execution.profile_hash == authorization.profile_hash,
        execution.discovery_scope_hash == authorization.discovery_scope_hash,
        execution.discovery_manifest_hash == authorization.discovery_manifest_hash,
        execution.discovery_run_hash == authorization.discovery_run_hash,
        execution.authorization_scope_hash == authorization.scope_hash,
        execution.authorization_hash == authorization.authorization_hash,
        execution.authorization_terminal_hash == authorization.terminal_hash,
    )
    if not all(expected_bindings):
        raise ExternalDocumentSourceConflictError("External provider bootstrap execution lineage drifted")

    expected_scope = _scope_hash(authorization=authorization, request_key=execution.request_key)
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("External provider bootstrap request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("External provider bootstrap completion integrity failed")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("External provider bootstrap receipt lifecycle is incomplete")
    prior: str | None = None
    for sequence_number, receipt in enumerate(rows, start=1):
        if receipt.sequence_number != sequence_number or receipt.prior_receipt_hash != prior:
            raise ExternalDocumentSourceConflictError("External provider bootstrap receipt chain linkage failed")
        if receipt.scope_hash != execution.scope_hash or receipt.actor_id != execution.requested_by_id:
            raise ExternalDocumentSourceConflictError("External provider bootstrap receipt scope or actor drifted")
        if any(bool(getattr(receipt, field)) for field in _SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("External provider bootstrap receipt safety boundary drifted")
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
        if (
            receipt.status_after != expected_status
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != execution.request_reason
            or receipt.decision_hash != expected_decision
            or receipt.authorization_consumed != expected_consumed
        ):
            raise ExternalDocumentSourceConflictError("External provider bootstrap receipt facts drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("External provider bootstrap receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_connection_bootstrap(
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
        select(ExternalDocumentSourceConnectionBootstrapExecution).where(
            ExternalDocumentSourceConnectionBootstrapExecution.organization_id == organization_id,
            ExternalDocumentSourceConnectionBootstrapExecution.profile_id == profile_id,
            ExternalDocumentSourceConnectionBootstrapExecution.authorization_id == authorization_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for consumed external provider authorization")
        authorization, _ = get_external_document_source_connection_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            now=existing.completed_at,
        )
        return existing, authorization, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceConnectionBootstrapExecution).where(
            ExternalDocumentSourceConnectionBootstrapExecution.organization_id == organization_id,
            ExternalDocumentSourceConnectionBootstrapExecution.profile_id == profile_id,
            ExternalDocumentSourceConnectionBootstrapExecution.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for external provider bootstrap request_key")

    current = _aware(now or _utc_now())
    authorization, outcome = get_external_document_source_connection_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
        now=current,
    )
    if outcome == "expired" or authorization.status != "authorized" or not authorization.live_connection_authorized:
        return None, authorization, "expired"
    if authorization.authorization_hash is None:
        raise ExternalDocumentSourceConflictError("External provider connection authorization approval hash is missing")

    scope_hash = _scope_hash(authorization=authorization, request_key=normalized_key)
    execution = ExternalDocumentSourceConnectionBootstrapExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        discovery_run_id=authorization.discovery_run_id,
        authorization_id=authorization.id,
        provider_kind=authorization.provider_kind,
        profile_hash=authorization.profile_hash,
        discovery_scope_hash=authorization.discovery_scope_hash,
        discovery_manifest_hash=authorization.discovery_manifest_hash,
        discovery_run_hash=authorization.discovery_run_hash,
        authorization_scope_hash=authorization.scope_hash,
        authorization_hash=authorization.authorization_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        authorization_consumed=False,
        **{field: False for field in _SAFETY_FIELDS},
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
        authorization_consumed=False,
    )

    _terminalize_expired(
        db,
        authorization,
        current=current,
        reason=_consumption_reason(execution.id),
    )
    if authorization.terminal_hash is None:
        raise ExternalDocumentSourceConflictError("External provider connection authorization terminal hash is missing")

    execution.status = "completed"
    execution.authorization_terminal_hash = authorization.terminal_hash
    execution.completed_at = current
    execution.authorization_consumed = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=execution.completion_hash,
        authorization_consumed=True,
    )
    db.flush()
    _ensure_authorization_integrity(db, authorization)
    _ensure_integrity(db, execution)
    return execution, authorization, "completed"


def get_external_document_source_connection_bootstrap_execution(
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


def list_external_document_source_connection_bootstrap_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_connection_bootstrap_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
