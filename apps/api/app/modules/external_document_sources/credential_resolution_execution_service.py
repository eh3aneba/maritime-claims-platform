from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.credential_reference_service import (
    get_external_document_source_credential_reference,
)
from app.modules.external_document_sources.credential_resolution_execution_models import (
    ExternalDocumentSourceCredentialResolutionExecution,
    ExternalDocumentSourceCredentialResolutionExecutionReceipt,
)
from app.modules.external_document_sources.provider_client_activation_execution_models import (
    ExternalDocumentSourceProviderClientActivationExecution,
)
from app.modules.external_document_sources.provider_client_activation_execution_service import (
    _ensure_integrity as _ensure_activation_execution_integrity,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)

_ALLOWED_BACKENDS = {
    "aws_secrets_manager",
    "azure_key_vault",
    "gcp_secret_manager",
    "hashicorp_vault",
}
_ALLOWED_FAILURE_CODES = {
    "reference_not_found",
    "reference_unresolved",
    "permission_denied",
    "backend_unavailable",
    "resolver_rejected",
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "oauth_authorization_code_stored",
    "oauth_token_exchanged",
    "access_token_stored",
    "refresh_token_stored",
    "client_secret_stored",
    "private_key_stored",
    "provider_client_activation_authorized",
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


@dataclass(frozen=True)
class CredentialReferenceResolutionResult:
    """Non-secret outcome returned by a credential resolver.

    A resolver may retrieve secret material internally, but the raw value must
    never cross this interface. The application service receives only this
    bounded success/failure result.
    """

    resolved: bool
    failure_code: str | None = None


class CredentialReferenceExecutionResolver(Protocol):
    resolver_kind: str

    def resolve(self, locator: CredentialReferenceLocator) -> CredentialReferenceResolutionResult: ...


_RESOLVERS: dict[str, CredentialReferenceExecutionResolver] = {}


def register_external_document_source_credential_resolution_resolver(
    backend: str,
    resolver: CredentialReferenceExecutionResolver,
) -> None:
    normalized_backend = backend.strip().lower()
    if normalized_backend not in _ALLOWED_BACKENDS:
        raise ValueError("Unsupported credential reference backend")
    resolver_kind = getattr(resolver, "resolver_kind", None)
    if not isinstance(resolver_kind, str) or not _SAFE_IDENTIFIER.fullmatch(resolver_kind):
        raise ValueError("Credential resolution resolver kind is invalid")
    _RESOLVERS[normalized_backend] = resolver


def clear_external_document_source_credential_resolution_resolvers() -> None:
    _RESOLVERS.clear()


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


def _normalize_resolver_kind(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError("Credential resolution resolver kind is invalid")
    return normalized


def _validate_resolution_result(result: CredentialReferenceResolutionResult) -> None:
    if not isinstance(result, CredentialReferenceResolutionResult):
        raise ExternalDocumentSourceConflictError("Credential resolution resolver returned an invalid result")
    if result.resolved:
        if result.failure_code is not None:
            raise ExternalDocumentSourceConflictError("Successful credential resolution cannot include a failure code")
        return
    if result.failure_code not in _ALLOWED_FAILURE_CODES:
        raise ExternalDocumentSourceConflictError("Credential resolution resolver returned an unsupported failure code")
    raise ExternalDocumentSourceConflictError(f"Credential reference resolution failed ({result.failure_code})")


def _scope_hash(
    *,
    activation_execution: ExternalDocumentSourceProviderClientActivationExecution,
    resolution_resolver_kind: str,
    request_key: str,
) -> str:
    if activation_execution.completion_hash is None or activation_execution.authorization_terminal_hash is None:
        raise ExternalDocumentSourceConflictError("Phase H activation execution completion facts are incomplete")
    return _canonical_hash(
        {
            "organization_id": str(activation_execution.organization_id),
            "profile_id": str(activation_execution.profile_id),
            "activation_execution_id": str(activation_execution.id),
            "authorization_id": str(activation_execution.authorization_id),
            "health_qualification_id": str(activation_execution.health_qualification_id),
            "credential_reference_binding_id": str(activation_execution.credential_reference_binding_id),
            "provider_kind": activation_execution.provider_kind,
            "profile_hash": activation_execution.profile_hash,
            "locator_hash": activation_execution.locator_hash,
            "reference_backend": activation_execution.reference_backend,
            "health_resolver_kind": activation_execution.resolver_kind,
            "health_result_hash": activation_execution.health_result_hash,
            "activation_execution_scope_hash": activation_execution.scope_hash,
            "activation_execution_request_hash": activation_execution.request_hash,
            "activation_execution_completion_hash": activation_execution.completion_hash,
            "activation_authorization_terminal_hash": activation_execution.authorization_terminal_hash,
            "resolution_resolver_kind": resolution_resolver_kind,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceCredentialResolutionExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            "credential_reference_stored": True,
            "credential_reference_resolution_performed": False,
            "activation_authorization_consumed": True,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _completion_hash(execution: ExternalDocumentSourceCredentialResolutionExecution) -> str:
    if execution.completed_at is None:
        raise ExternalDocumentSourceConflictError("Credential resolution completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "completed_at": _iso(execution.completed_at),
            "credential_reference_stored": True,
            "credential_reference_resolution_performed": True,
            "activation_authorization_consumed": True,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceCredentialResolutionExecutionReceipt) -> str:
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
            "credential_reference_resolution_performed": receipt.credential_reference_resolution_performed,
            "activation_authorization_consumed": True,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceCredentialResolutionExecution:
    row = db.scalar(
        select(ExternalDocumentSourceCredentialResolutionExecution).where(
            ExternalDocumentSourceCredentialResolutionExecution.id == execution_id,
            ExternalDocumentSourceCredentialResolutionExecution.organization_id == organization_id,
            ExternalDocumentSourceCredentialResolutionExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Credential resolution execution not found")
    return row


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceCredentialResolutionExecution,
) -> list[ExternalDocumentSourceCredentialResolutionExecutionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceCredentialResolutionExecutionReceipt)
            .where(
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceCredentialResolutionExecutionReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceCredentialResolutionExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
    resolution_performed: bool,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceCredentialResolutionExecutionReceipt(
        organization_id=execution.organization_id,
        execution_id=execution.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=execution.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=execution.request_reason,
        scope_hash=execution.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        credential_reference_stored=True,
        credential_reference_resolution_performed=resolution_performed,
        activation_authorization_consumed=True,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _activation_execution(
    db: Session,
    execution: ExternalDocumentSourceCredentialResolutionExecution,
) -> ExternalDocumentSourceProviderClientActivationExecution:
    row = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationExecution).where(
            ExternalDocumentSourceProviderClientActivationExecution.id == execution.activation_execution_id,
            ExternalDocumentSourceProviderClientActivationExecution.organization_id == execution.organization_id,
            ExternalDocumentSourceProviderClientActivationExecution.profile_id == execution.profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase H activation execution lineage is missing")
    return row


def _active_binding(db: Session, activation_execution: ExternalDocumentSourceProviderClientActivationExecution):
    binding = get_external_document_source_credential_reference(
        db,
        organization_id=activation_execution.organization_id,
        profile_id=activation_execution.profile_id,
        binding_id=activation_execution.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("Bound credential reference is not active")
    if (
        binding.provider_kind != activation_execution.provider_kind
        or binding.profile_hash != activation_execution.profile_hash
        or binding.locator_hash != activation_execution.locator_hash
        or binding.reference_backend != activation_execution.reference_backend
        or binding.scope_hash != activation_execution.binding_scope_hash
        or binding.request_hash != activation_execution.binding_request_hash
        or binding.approval_hash != activation_execution.binding_approval_hash
    ):
        raise ExternalDocumentSourceConflictError("Credential resolution upstream binding lineage drifted")
    return binding


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceCredentialResolutionExecution) -> None:
    if execution.status != "completed" or not execution.credential_reference_resolution_performed:
        raise ExternalDocumentSourceConflictError("Credential resolution execution lifecycle is incomplete")
    if not execution.credential_reference_stored or not execution.activation_authorization_consumed:
        raise ExternalDocumentSourceConflictError("Credential resolution inherited governance facts drifted")
    if any(bool(getattr(execution, field)) for field in _FALSE_SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("Credential resolution execution safety boundary drifted")

    activation_execution = _activation_execution(db, execution)
    _ensure_activation_execution_integrity(db, activation_execution)
    _active_binding(db, activation_execution)
    if activation_execution.status != "completed" or not activation_execution.activation_authorization_consumed:
        raise ExternalDocumentSourceConflictError("Phase H activation execution is not complete")
    if activation_execution.completion_hash is None or activation_execution.authorization_terminal_hash is None:
        raise ExternalDocumentSourceConflictError("Phase H activation execution completion lineage is incomplete")

    if (
        execution.authorization_id != activation_execution.authorization_id
        or execution.health_qualification_id != activation_execution.health_qualification_id
        or execution.credential_reference_binding_id != activation_execution.credential_reference_binding_id
        or execution.provider_kind != activation_execution.provider_kind
        or execution.profile_hash != activation_execution.profile_hash
        or execution.locator_hash != activation_execution.locator_hash
        or execution.reference_backend != activation_execution.reference_backend
        or execution.health_resolver_kind != activation_execution.resolver_kind
        or execution.health_result_hash != activation_execution.health_result_hash
        or execution.activation_execution_scope_hash != activation_execution.scope_hash
        or execution.activation_execution_request_hash != activation_execution.request_hash
        or execution.activation_execution_completion_hash != activation_execution.completion_hash
        or execution.activation_authorization_terminal_hash != activation_execution.authorization_terminal_hash
    ):
        raise ExternalDocumentSourceConflictError("Credential resolution execution lineage drifted")

    resolution_kind = _normalize_resolver_kind(execution.resolution_resolver_kind)
    expected_scope = _scope_hash(
        activation_execution=activation_execution,
        resolution_resolver_kind=resolution_kind,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Credential resolution request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Credential resolution completion integrity failed")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Credential resolution timestamps drifted")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Credential resolution receipt lifecycle is incomplete")
    expected = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior: str | None = None
    for receipt, facts in zip(rows, expected, strict=True):
        sequence, status_after, occurred_at, decision_hash, resolution_performed = facts
        if (
            receipt.sequence_number != sequence
            or receipt.event_type != status_after
            or receipt.status_after != status_after
            or receipt.actor_id != execution.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != execution.request_reason
            or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
            or not receipt.credential_reference_stored
            or not receipt.activation_authorization_consumed
            or receipt.credential_reference_resolution_performed != resolution_performed
        ):
            raise ExternalDocumentSourceConflictError("Credential resolution receipt facts drifted")
        if any(bool(getattr(receipt, field)) for field in _FALSE_SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("Credential resolution receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Credential resolution receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_credential_resolution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    activation_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceCredentialResolutionExecution).where(
            ExternalDocumentSourceCredentialResolutionExecution.organization_id == organization_id,
            ExternalDocumentSourceCredentialResolutionExecution.profile_id == profile_id,
            ExternalDocumentSourceCredentialResolutionExecution.activation_execution_id == activation_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for credential resolution execution")
        return existing, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceCredentialResolutionExecution).where(
            ExternalDocumentSourceCredentialResolutionExecution.organization_id == organization_id,
            ExternalDocumentSourceCredentialResolutionExecution.profile_id == profile_id,
            ExternalDocumentSourceCredentialResolutionExecution.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for credential resolution request_key")

    activation_execution = db.scalar(
        select(ExternalDocumentSourceProviderClientActivationExecution)
        .where(
            ExternalDocumentSourceProviderClientActivationExecution.id == activation_execution_id,
            ExternalDocumentSourceProviderClientActivationExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientActivationExecution.profile_id == profile_id,
        )
        .with_for_update()
    )
    if activation_execution is None:
        raise ExternalDocumentSourceNotFoundError("Phase H activation execution not found")

    existing = db.scalar(
        select(ExternalDocumentSourceCredentialResolutionExecution).where(
            ExternalDocumentSourceCredentialResolutionExecution.activation_execution_id == activation_execution_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for credential resolution execution")
        return existing, "unchanged"

    _ensure_activation_execution_integrity(db, activation_execution)
    if activation_execution.status != "completed" or not activation_execution.activation_authorization_consumed:
        raise ExternalDocumentSourceConflictError("Phase H activation execution is not eligible for credential resolution")
    if activation_execution.completion_hash is None or activation_execution.authorization_terminal_hash is None:
        raise ExternalDocumentSourceConflictError("Phase H activation execution completion lineage is incomplete")

    binding = _active_binding(db, activation_execution)
    resolver = _RESOLVERS.get(binding.reference_backend)
    if resolver is None:
        raise ExternalDocumentSourceConflictError("Credential resolution resolver is unavailable")
    resolution_resolver_kind = _normalize_resolver_kind(resolver.resolver_kind)
    current = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        activation_execution=activation_execution,
        resolution_resolver_kind=resolution_resolver_kind,
        request_key=normalized_key,
    )

    execution = ExternalDocumentSourceCredentialResolutionExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        activation_execution_id=activation_execution.id,
        authorization_id=activation_execution.authorization_id,
        health_qualification_id=activation_execution.health_qualification_id,
        credential_reference_binding_id=activation_execution.credential_reference_binding_id,
        provider_kind=activation_execution.provider_kind,
        profile_hash=activation_execution.profile_hash,
        locator_hash=activation_execution.locator_hash,
        reference_backend=activation_execution.reference_backend,
        health_resolver_kind=activation_execution.resolver_kind,
        resolution_resolver_kind=resolution_resolver_kind,
        health_result_hash=activation_execution.health_result_hash,
        activation_execution_scope_hash=activation_execution.scope_hash,
        activation_execution_request_hash=activation_execution.request_hash,
        activation_execution_completion_hash=activation_execution.completion_hash,
        activation_authorization_terminal_hash=activation_execution.authorization_terminal_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        credential_reference_stored=True,
        credential_reference_resolution_performed=False,
        activation_authorization_consumed=True,
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
        decision_hash=execution.request_hash,
        resolution_performed=False,
    )

    locator = CredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    try:
        result = resolver.resolve(locator)
    except Exception:
        raise ExternalDocumentSourceConflictError("Credential reference resolution failed") from None
    _validate_resolution_result(result)

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.completed_at = completed_at
    execution.credential_reference_resolution_performed = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=completed_at,
        decision_hash=execution.completion_hash,
        resolution_performed=True,
    )
    db.flush()
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_credential_resolution_execution(
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


def list_external_document_source_credential_resolution_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_credential_resolution_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
