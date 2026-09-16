from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.credential_reference_service import get_external_document_source_credential_reference
from app.modules.external_document_sources.provider_client_health_models import (
    ExternalDocumentSourceProviderClientHealthExecution,
    ExternalDocumentSourceProviderClientHealthReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
)
from app.modules.external_document_sources.token_acquisition_execution_models import (
    ExternalDocumentSourceTokenAcquisitionExecution,
)
from app.modules.external_document_sources.token_acquisition_execution_service import (
    _ensure_integrity as _ensure_token_acquisition_integrity,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_LATENCY_CLASSES = {"fast", "normal", "slow", "unknown"}
_ALLOWED_FAILURE_CODES = {
    "unauthorized",
    "permission_denied",
    "endpoint_unavailable",
    "timeout",
    "malformed_response",
    "oversized_response",
    "provider_rejected",
}
_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "oauth_authorization_code_stored",
    "access_token_stored",
    "refresh_token_stored",
    "id_token_stored",
    "client_secret_stored",
    "private_key_stored",
    "provider_client_stored",
    "provider_response_body_stored",
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
_PROVIDER_HEALTH_POLICIES = {
    "sharepoint": {
        "token_flow_kind": "client_credentials",
        "client_kind": "microsoft_graph_transient_v1",
        "health_operation_kind": "graph_organization_health",
        "provider_origin": "https://graph.microsoft.com",
        "health_endpoint_url": "https://graph.microsoft.com/v1.0/organization?$select=id",
        "audience_kind": "microsoft_graph_default",
    },
    "google_drive": {
        "token_flow_kind": "jwt_bearer",
        "client_kind": "google_drive_transient_v3",
        "health_operation_kind": "drive_about_health",
        "provider_origin": "https://www.googleapis.com",
        "health_endpoint_url": "https://www.googleapis.com/drive/v3/about?fields=user(permissionId)",
        "audience_kind": "google_drive_readonly",
    },
}


@dataclass(frozen=True)
class ProviderClientHealthPolicy:
    provider_kind: str
    token_flow_kind: str
    client_kind: str
    health_operation_kind: str
    provider_origin: str
    health_endpoint_url: str
    audience_kind: str
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 5.0
    total_timeout_seconds: float = 8.0
    max_response_bytes: int = 65536
    allow_redirects: bool = False


@dataclass(frozen=True)
class ProviderClientHealthResult:
    """Bounded non-secret result returned after transient client construction and health qualification."""

    healthy: bool
    failure_code: str | None = None
    latency_class: str | None = None


class ExternalDocumentSourceProviderClientHealthAdapter(Protocol):
    adapter_kind: str
    provider_kind: str
    client_kind: str
    health_operation_kind: str
    provider_origin: str

    def qualify(
        self,
        locator: CredentialReferenceLocator,
        policy: ProviderClientHealthPolicy,
    ) -> ProviderClientHealthResult: ...


_HEALTH_ADAPTERS: dict[tuple[str, str], ExternalDocumentSourceProviderClientHealthAdapter] = {}


def register_external_document_source_provider_client_health_adapter(
    provider_kind: str,
    health_operation_kind: str,
    adapter: ExternalDocumentSourceProviderClientHealthAdapter,
) -> None:
    provider = provider_kind.strip().lower()
    operation = health_operation_kind.strip().lower()
    expected = _PROVIDER_HEALTH_POLICIES.get(provider)
    if expected is None or operation != expected["health_operation_kind"]:
        raise ValueError("Unsupported provider/health-operation combination")
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_IDENTIFIER.fullmatch(adapter_kind):
        raise ValueError("Provider client health adapter kind is invalid")
    if getattr(adapter, "provider_kind", None) != provider:
        raise ValueError("Provider client health adapter provider kind does not match the governed provider")
    if getattr(adapter, "client_kind", None) != expected["client_kind"]:
        raise ValueError("Provider client health adapter client kind is not approved")
    if getattr(adapter, "health_operation_kind", None) != operation:
        raise ValueError("Provider client health adapter operation does not match the governed operation")
    origin = getattr(adapter, "provider_origin", None)
    if origin != expected["provider_origin"]:
        raise ValueError("Provider client health adapter origin is not approved")
    parsed = urlparse(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Provider client health adapter origin is invalid")
    _HEALTH_ADAPTERS[(provider, operation)] = adapter


def clear_external_document_source_provider_client_health_adapters() -> None:
    _HEALTH_ADAPTERS.clear()


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
        raise ExternalDocumentSourceValidationError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError(f"{field} is invalid")
    return normalized


def _health_policy(provider_kind: str) -> ProviderClientHealthPolicy:
    provider = provider_kind.strip().lower()
    base = _PROVIDER_HEALTH_POLICIES.get(provider)
    if base is None:
        raise ExternalDocumentSourceConflictError("Unsupported external document source provider for client health")
    endpoint = base["health_endpoint_url"]
    parsed_endpoint = urlparse(endpoint)
    parsed_origin = urlparse(base["provider_origin"])
    if (
        parsed_endpoint.scheme != "https"
        or parsed_endpoint.netloc != parsed_origin.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.fragment
    ):
        raise ExternalDocumentSourceConflictError("Derived provider health endpoint is not approved")
    return ProviderClientHealthPolicy(
        provider_kind=provider,
        token_flow_kind=base["token_flow_kind"],
        client_kind=base["client_kind"],
        health_operation_kind=base["health_operation_kind"],
        provider_origin=base["provider_origin"],
        health_endpoint_url=endpoint,
        audience_kind=base["audience_kind"],
    )


def _endpoint_policy_hash(policy: ProviderClientHealthPolicy) -> str:
    return _canonical_hash(
        {
            "provider_kind": policy.provider_kind,
            "token_flow_kind": policy.token_flow_kind,
            "client_kind": policy.client_kind,
            "health_operation_kind": policy.health_operation_kind,
            "provider_origin": policy.provider_origin,
            "health_endpoint_url": policy.health_endpoint_url,
            "audience_kind": policy.audience_kind,
            "connect_timeout_seconds": policy.connect_timeout_seconds,
            "read_timeout_seconds": policy.read_timeout_seconds,
            "total_timeout_seconds": policy.total_timeout_seconds,
            "max_response_bytes": policy.max_response_bytes,
            "allow_redirects": policy.allow_redirects,
        }
    )


def _validate_result(result: ProviderClientHealthResult) -> None:
    if not isinstance(result, ProviderClientHealthResult):
        raise ExternalDocumentSourceConflictError("Provider client health adapter returned an invalid result")
    if result.healthy:
        if result.failure_code is not None:
            raise ExternalDocumentSourceConflictError("Successful provider client health qualification cannot include a failure code")
        if result.latency_class not in _ALLOWED_LATENCY_CLASSES:
            raise ExternalDocumentSourceConflictError("Provider client health adapter returned an invalid latency class")
        return
    if result.failure_code not in _ALLOWED_FAILURE_CODES:
        raise ExternalDocumentSourceConflictError("Provider client health adapter returned an unsupported failure code")
    if result.latency_class is not None:
        raise ExternalDocumentSourceConflictError("Failed provider client health qualification cannot include a latency class")
    raise ExternalDocumentSourceConflictError(f"Provider client health qualification failed ({result.failure_code})")


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "provider_client_constructed": executed,
        "provider_network_health_performed": executed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _scope_hash(
    *,
    token_execution: ExternalDocumentSourceTokenAcquisitionExecution,
    client_kind: str,
    health_operation_kind: str,
    health_adapter_kind: str,
    endpoint_policy_hash: str,
    request_key: str,
) -> str:
    if token_execution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase J token acquisition completion facts are incomplete")
    return _canonical_hash(
        {
            "organization_id": str(token_execution.organization_id),
            "profile_id": str(token_execution.profile_id),
            "token_acquisition_execution_id": str(token_execution.id),
            "credential_resolution_execution_id": str(token_execution.credential_resolution_execution_id),
            "credential_reference_binding_id": str(token_execution.credential_reference_binding_id),
            "provider_kind": token_execution.provider_kind,
            "profile_hash": token_execution.profile_hash,
            "locator_hash": token_execution.locator_hash,
            "reference_backend": token_execution.reference_backend,
            "resolution_resolver_kind": token_execution.resolution_resolver_kind,
            "token_flow_kind": token_execution.token_flow_kind,
            "token_acquirer_kind": token_execution.acquirer_kind,
            "token_acquisition_scope_hash": token_execution.scope_hash,
            "token_acquisition_request_hash": token_execution.request_hash,
            "token_acquisition_completion_hash": token_execution.completion_hash,
            "client_kind": client_kind,
            "health_operation_kind": health_operation_kind,
            "health_adapter_kind": health_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceProviderClientHealthExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceProviderClientHealthExecution) -> str:
    if execution.completed_at is None or execution.result_status != "healthy" or execution.latency_class is None:
        raise ExternalDocumentSourceConflictError("Provider client health completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "result_status": execution.result_status,
            "latency_class": execution.latency_class,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceProviderClientHealthReceipt) -> str:
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
            **_base_safety(receipt.event_type == "completed"),
        }
    )


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceProviderClientHealthExecution,
) -> list[ExternalDocumentSourceProviderClientHealthReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceProviderClientHealthReceipt)
            .where(
                ExternalDocumentSourceProviderClientHealthReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceProviderClientHealthReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceProviderClientHealthReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceProviderClientHealthExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceProviderClientHealthReceipt(
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
        **_base_safety(event_type == "completed"),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceProviderClientHealthExecution:
    row = db.scalar(
        select(ExternalDocumentSourceProviderClientHealthExecution).where(
            ExternalDocumentSourceProviderClientHealthExecution.id == execution_id,
            ExternalDocumentSourceProviderClientHealthExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientHealthExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Provider client health execution not found")
    return row


def _token_execution(
    db: Session,
    execution: ExternalDocumentSourceProviderClientHealthExecution,
) -> ExternalDocumentSourceTokenAcquisitionExecution:
    row = db.scalar(
        select(ExternalDocumentSourceTokenAcquisitionExecution).where(
            ExternalDocumentSourceTokenAcquisitionExecution.id == execution.token_acquisition_execution_id,
            ExternalDocumentSourceTokenAcquisitionExecution.organization_id == execution.organization_id,
            ExternalDocumentSourceTokenAcquisitionExecution.profile_id == execution.profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase J token acquisition lineage is missing")
    return row


def _active_binding(db: Session, token_execution: ExternalDocumentSourceTokenAcquisitionExecution):
    binding = get_external_document_source_credential_reference(
        db,
        organization_id=token_execution.organization_id,
        profile_id=token_execution.profile_id,
        binding_id=token_execution.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("Bound credential reference is not active")
    if (
        binding.provider_kind != token_execution.provider_kind
        or binding.profile_hash != token_execution.profile_hash
        or binding.locator_hash != token_execution.locator_hash
        or binding.reference_backend != token_execution.reference_backend
    ):
        raise ExternalDocumentSourceConflictError("Provider client health credential-reference lineage drifted")
    return binding


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceProviderClientHealthExecution) -> None:
    if execution.status != "completed" or execution.result_status != "healthy" or execution.latency_class not in _ALLOWED_LATENCY_CLASSES:
        raise ExternalDocumentSourceConflictError("Provider client health execution lifecycle is incomplete")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Provider client health execution safety boundary drifted")

    token_execution = _token_execution(db, execution)
    _ensure_token_acquisition_integrity(db, token_execution)
    if token_execution.status != "completed" or token_execution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase J token acquisition is not complete")
    _active_binding(db, token_execution)

    profile = _get_profile(db, organization_id=execution.organization_id, profile_id=execution.profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != execution.profile_hash:
        raise ExternalDocumentSourceConflictError("Provider client health source profile is not active")
    policy = _health_policy(profile.provider_kind)
    expected_policy_hash = _endpoint_policy_hash(policy)
    if (
        execution.credential_resolution_execution_id != token_execution.credential_resolution_execution_id
        or execution.credential_reference_binding_id != token_execution.credential_reference_binding_id
        or execution.provider_kind != token_execution.provider_kind
        or execution.profile_hash != token_execution.profile_hash
        or execution.locator_hash != token_execution.locator_hash
        or execution.reference_backend != token_execution.reference_backend
        or execution.resolution_resolver_kind != token_execution.resolution_resolver_kind
        or execution.token_flow_kind != token_execution.token_flow_kind
        or execution.token_acquirer_kind != token_execution.acquirer_kind
        or execution.token_acquisition_scope_hash != token_execution.scope_hash
        or execution.token_acquisition_request_hash != token_execution.request_hash
        or execution.token_acquisition_completion_hash != token_execution.completion_hash
        or execution.client_kind != policy.client_kind
        or execution.health_operation_kind != policy.health_operation_kind
        or execution.endpoint_policy_hash != expected_policy_hash
    ):
        raise ExternalDocumentSourceConflictError("Provider client health execution lineage drifted")
    adapter_kind = _normalize_identifier(execution.health_adapter_kind, field="Provider client health adapter kind")
    expected_scope = _scope_hash(
        token_execution=token_execution,
        client_kind=policy.client_kind,
        health_operation_kind=policy.health_operation_kind,
        health_adapter_kind=adapter_kind,
        endpoint_policy_hash=expected_policy_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Provider client health request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Provider client health completion integrity failed")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Provider client health timestamps drifted")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Provider client health receipt lifecycle is incomplete")
    expected_rows = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior: str | None = None
    for receipt, facts in zip(rows, expected_rows, strict=True):
        sequence, status_after, occurred_at, decision_hash, performed = facts
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
        ):
            raise ExternalDocumentSourceConflictError("Provider client health receipt facts drifted")
        for field, expected in _base_safety(performed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Provider client health receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Provider client health receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_provider_client_health(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    token_acquisition_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    existing = db.scalar(
        select(ExternalDocumentSourceProviderClientHealthExecution).where(
            ExternalDocumentSourceProviderClientHealthExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientHealthExecution.profile_id == profile_id,
            ExternalDocumentSourceProviderClientHealthExecution.token_acquisition_execution_id == token_acquisition_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for provider client health execution")
        return existing, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceProviderClientHealthExecution).where(
            ExternalDocumentSourceProviderClientHealthExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientHealthExecution.profile_id == profile_id,
            ExternalDocumentSourceProviderClientHealthExecution.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for provider client health request_key")

    token_execution = db.scalar(
        select(ExternalDocumentSourceTokenAcquisitionExecution)
        .where(
            ExternalDocumentSourceTokenAcquisitionExecution.id == token_acquisition_execution_id,
            ExternalDocumentSourceTokenAcquisitionExecution.organization_id == organization_id,
            ExternalDocumentSourceTokenAcquisitionExecution.profile_id == profile_id,
        )
        .with_for_update()
    )
    if token_execution is None:
        raise ExternalDocumentSourceNotFoundError("Phase J token acquisition execution not found")

    existing = db.scalar(
        select(ExternalDocumentSourceProviderClientHealthExecution).where(
            ExternalDocumentSourceProviderClientHealthExecution.token_acquisition_execution_id == token_acquisition_execution_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for provider client health execution")
        return existing, "unchanged"

    _ensure_token_acquisition_integrity(db, token_execution)
    if token_execution.status != "completed" or token_execution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase J token acquisition is not eligible for provider client health")
    binding = _active_binding(db, token_execution)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != token_execution.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")

    policy = _health_policy(profile.provider_kind)
    if token_execution.token_flow_kind != policy.token_flow_kind:
        raise ExternalDocumentSourceConflictError("Provider client health token-flow lineage drifted")
    adapter = _HEALTH_ADAPTERS.get((profile.provider_kind, policy.health_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Provider client health adapter is unavailable")
    adapter_kind = _normalize_identifier(adapter.adapter_kind, field="Provider client health adapter kind")
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.health_operation_kind != policy.health_operation_kind
        or adapter.provider_origin != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError("Provider client health adapter policy drifted")

    endpoint_policy_hash = _endpoint_policy_hash(policy)
    current = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        token_execution=token_execution,
        client_kind=policy.client_kind,
        health_operation_kind=policy.health_operation_kind,
        health_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution = ExternalDocumentSourceProviderClientHealthExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        token_acquisition_execution_id=token_execution.id,
        credential_resolution_execution_id=token_execution.credential_resolution_execution_id,
        credential_reference_binding_id=token_execution.credential_reference_binding_id,
        provider_kind=token_execution.provider_kind,
        profile_hash=token_execution.profile_hash,
        locator_hash=token_execution.locator_hash,
        reference_backend=token_execution.reference_backend,
        resolution_resolver_kind=token_execution.resolution_resolver_kind,
        token_flow_kind=token_execution.token_flow_kind,
        token_acquirer_kind=token_execution.acquirer_kind,
        token_acquisition_scope_hash=token_execution.scope_hash,
        token_acquisition_request_hash=token_execution.request_hash,
        token_acquisition_completion_hash=token_execution.completion_hash,
        client_kind=policy.client_kind,
        health_operation_kind=policy.health_operation_kind,
        health_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        **_base_safety(False),
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
    )

    locator = CredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    try:
        result = adapter.qualify(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Provider client health qualification failed") from None
    _validate_result(result)

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.result_status = "healthy"
    execution.latency_class = result.latency_class
    execution.completed_at = completed_at
    execution.provider_client_constructed = True
    execution.provider_network_health_performed = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=completed_at,
        decision_hash=execution.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_provider_client_health(
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


def list_external_document_source_provider_client_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_provider_client_health(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
