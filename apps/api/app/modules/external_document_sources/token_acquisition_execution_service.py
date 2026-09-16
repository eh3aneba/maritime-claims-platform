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
from app.modules.external_document_sources.credential_resolution_execution_models import ExternalDocumentSourceCredentialResolutionExecution
from app.modules.external_document_sources.credential_resolution_execution_service import _ensure_integrity as _ensure_credential_resolution_integrity
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
)
from app.modules.external_document_sources.token_acquisition_execution_models import (
    ExternalDocumentSourceTokenAcquisitionExecution,
    ExternalDocumentSourceTokenAcquisitionExecutionReceipt,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_TENANT_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_ALLOWED_EXPIRY_CLASSES = {"short", "standard", "long", "unknown"}
_ALLOWED_FAILURE_CODES = {
    "invalid_client", "invalid_grant", "unauthorized_client", "invalid_scope", "permission_denied",
    "endpoint_unavailable", "timeout", "malformed_response", "oversized_response", "provider_rejected",
}
_FALSE_SAFETY_FIELDS = (
    "credential_stored", "oauth_authorization_code_stored", "access_token_stored", "refresh_token_stored",
    "id_token_stored", "client_secret_stored", "private_key_stored", "provider_client_constructed",
    "provider_data_api_performed", "remote_list_performed", "remote_read_performed", "remote_write_performed",
    "remote_delete_performed", "subscription_created", "checkpoint_created", "sync_executed", "evidence_admitted",
    "document_created", "claim_mutated",
)


@dataclass(frozen=True)
class TokenAcquisitionPolicy:
    provider_kind: str
    token_flow_kind: str
    token_endpoint_url: str
    audience_kind: str
    tenant_hint: str | None
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 5.0
    total_timeout_seconds: float = 8.0
    max_response_bytes: int = 65536
    allow_redirects: bool = False


@dataclass(frozen=True)
class TokenAcquisitionResult:
    """Bounded non-secret result. Secret/token material must never cross this interface."""

    acquired: bool
    failure_code: str | None = None
    expiry_class: str | None = None


class ExternalDocumentSourceTokenAcquirer(Protocol):
    acquirer_kind: str
    provider_kind: str
    token_flow_kind: str
    token_endpoint_origin: str

    def acquire(self, locator: CredentialReferenceLocator, policy: TokenAcquisitionPolicy) -> TokenAcquisitionResult: ...


_TOKEN_ACQUIRERS: dict[tuple[str, str], ExternalDocumentSourceTokenAcquirer] = {}
_PROVIDER_POLICIES = {
    "sharepoint": {
        "token_flow_kind": "client_credentials",
        "token_endpoint_origin": "https://login.microsoftonline.com",
        "audience_kind": "microsoft_graph_default",
    },
    "google_drive": {
        "token_flow_kind": "jwt_bearer",
        "token_endpoint_origin": "https://oauth2.googleapis.com",
        "audience_kind": "google_drive_readonly",
    },
}


def register_external_document_source_token_acquirer(provider_kind: str, token_flow_kind: str, acquirer: ExternalDocumentSourceTokenAcquirer) -> None:
    provider = provider_kind.strip().lower()
    flow = token_flow_kind.strip().lower()
    expected = _PROVIDER_POLICIES.get(provider)
    if expected is None or flow != expected["token_flow_kind"]:
        raise ValueError("Unsupported provider/token-flow combination")
    acquirer_kind = getattr(acquirer, "acquirer_kind", None)
    if not isinstance(acquirer_kind, str) or not _SAFE_IDENTIFIER.fullmatch(acquirer_kind):
        raise ValueError("Token acquirer kind is invalid")
    if getattr(acquirer, "provider_kind", None) != provider:
        raise ValueError("Token acquirer provider kind does not match the governed provider")
    if getattr(acquirer, "token_flow_kind", None) != flow:
        raise ValueError("Token acquirer flow does not match the governed token flow")
    origin = getattr(acquirer, "token_endpoint_origin", None)
    if origin != expected["token_endpoint_origin"]:
        raise ValueError("Token acquirer endpoint origin is not approved")
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Token acquirer endpoint origin is invalid")
    _TOKEN_ACQUIRERS[(provider, flow)] = acquirer


def clear_external_document_source_token_acquirers() -> None:
    _TOKEN_ACQUIRERS.clear()


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


def _token_policy(provider_kind: str, normalized_config: dict) -> TokenAcquisitionPolicy:
    provider = provider_kind.strip().lower()
    base = _PROVIDER_POLICIES.get(provider)
    if base is None:
        raise ExternalDocumentSourceConflictError("Unsupported external document source provider for token acquisition")
    if provider == "sharepoint":
        tenant = normalized_config.get("tenant_domain")
        if not isinstance(tenant, str) or not _SAFE_TENANT_DOMAIN.fullmatch(tenant):
            raise ExternalDocumentSourceConflictError("Governed SharePoint tenant domain is invalid for token acquisition")
        endpoint = f"{base['token_endpoint_origin']}/{tenant}/oauth2/v2.0/token"
        tenant_hint = tenant
    else:
        expected_keys = {"shared_drive_id", "folder_id"}
        if not isinstance(normalized_config, dict) or not set(normalized_config).issubset(expected_keys):
            raise ExternalDocumentSourceConflictError("Governed Google Drive profile configuration drifted")
        endpoint = f"{base['token_endpoint_origin']}/token"
        tenant_hint = None
    parsed = urlparse(endpoint)
    actual_origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.scheme != "https" or actual_origin != base["token_endpoint_origin"] or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ExternalDocumentSourceConflictError("Derived token endpoint is not approved")
    return TokenAcquisitionPolicy(
        provider_kind=provider,
        token_flow_kind=base["token_flow_kind"],
        token_endpoint_url=endpoint,
        audience_kind=base["audience_kind"],
        tenant_hint=tenant_hint,
    )


def _endpoint_policy_hash(policy: TokenAcquisitionPolicy) -> str:
    return _canonical_hash({
        "provider_kind": policy.provider_kind,
        "token_flow_kind": policy.token_flow_kind,
        "token_endpoint_url": policy.token_endpoint_url,
        "audience_kind": policy.audience_kind,
        "tenant_hint": policy.tenant_hint,
        "connect_timeout_seconds": policy.connect_timeout_seconds,
        "read_timeout_seconds": policy.read_timeout_seconds,
        "total_timeout_seconds": policy.total_timeout_seconds,
        "max_response_bytes": policy.max_response_bytes,
        "allow_redirects": policy.allow_redirects,
    })


def _validate_result(result: TokenAcquisitionResult) -> None:
    if not isinstance(result, TokenAcquisitionResult):
        raise ExternalDocumentSourceConflictError("Token acquirer returned an invalid result")
    if result.acquired:
        if result.failure_code is not None:
            raise ExternalDocumentSourceConflictError("Successful token acquisition cannot include a failure code")
        if result.expiry_class not in _ALLOWED_EXPIRY_CLASSES:
            raise ExternalDocumentSourceConflictError("Token acquirer returned an invalid expiry class")
        return
    if result.failure_code not in _ALLOWED_FAILURE_CODES:
        raise ExternalDocumentSourceConflictError("Token acquirer returned an unsupported failure code")
    if result.expiry_class is not None:
        raise ExternalDocumentSourceConflictError("Failed token acquisition cannot include an expiry class")
    raise ExternalDocumentSourceConflictError(f"Token acquisition failed ({result.failure_code})")


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "token_acquisition_performed": executed,
        "oauth_token_exchanged": executed,
        "token_endpoint_network_performed": executed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _scope_hash(*, resolution: ExternalDocumentSourceCredentialResolutionExecution, token_flow_kind: str, acquirer_kind: str, endpoint_policy_hash: str, request_key: str) -> str:
    if resolution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase I credential resolution completion facts are incomplete")
    return _canonical_hash({
        "organization_id": str(resolution.organization_id),
        "profile_id": str(resolution.profile_id),
        "credential_resolution_execution_id": str(resolution.id),
        "activation_execution_id": str(resolution.activation_execution_id),
        "authorization_id": str(resolution.authorization_id),
        "health_qualification_id": str(resolution.health_qualification_id),
        "credential_reference_binding_id": str(resolution.credential_reference_binding_id),
        "provider_kind": resolution.provider_kind,
        "profile_hash": resolution.profile_hash,
        "locator_hash": resolution.locator_hash,
        "reference_backend": resolution.reference_backend,
        "resolution_resolver_kind": resolution.resolution_resolver_kind,
        "credential_resolution_scope_hash": resolution.scope_hash,
        "credential_resolution_request_hash": resolution.request_hash,
        "credential_resolution_completion_hash": resolution.completion_hash,
        "token_flow_kind": token_flow_kind,
        "acquirer_kind": acquirer_kind,
        "endpoint_policy_hash": endpoint_policy_hash,
        "request_key": request_key,
    })


def _request_hash(execution: ExternalDocumentSourceTokenAcquisitionExecution) -> str:
    return _canonical_hash({
        "execution_id": str(execution.id),
        "scope_hash": execution.scope_hash,
        "requested_by_id": str(execution.requested_by_id),
        "request_reason": execution.request_reason,
        "requested_at": _iso(execution.requested_at),
        **_base_safety(False),
    })


def _completion_hash(execution: ExternalDocumentSourceTokenAcquisitionExecution) -> str:
    if execution.completed_at is None or execution.result_status != "acquired" or execution.expiry_class is None:
        raise ExternalDocumentSourceConflictError("Token acquisition completion facts are incomplete")
    return _canonical_hash({
        "execution_id": str(execution.id),
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "result_status": execution.result_status,
        "expiry_class": execution.expiry_class,
        "completed_at": _iso(execution.completed_at),
        **_base_safety(True),
    })


def _receipt_hash(receipt: ExternalDocumentSourceTokenAcquisitionExecutionReceipt) -> str:
    return _canonical_hash({
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
    })


def _receipts(db: Session, execution: ExternalDocumentSourceTokenAcquisitionExecution) -> list[ExternalDocumentSourceTokenAcquisitionExecutionReceipt]:
    return list(db.scalars(select(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).where(
        ExternalDocumentSourceTokenAcquisitionExecutionReceipt.organization_id == execution.organization_id,
        ExternalDocumentSourceTokenAcquisitionExecutionReceipt.execution_id == execution.id,
    ).order_by(ExternalDocumentSourceTokenAcquisitionExecutionReceipt.sequence_number.asc())).all())


def _append_receipt(db: Session, *, execution: ExternalDocumentSourceTokenAcquisitionExecution, event_type: str, actor_id: UUID, occurred_at: datetime, decision_hash: str) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceTokenAcquisitionExecutionReceipt(
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


def _get_execution(db: Session, *, organization_id: UUID, profile_id: UUID, execution_id: UUID) -> ExternalDocumentSourceTokenAcquisitionExecution:
    row = db.scalar(select(ExternalDocumentSourceTokenAcquisitionExecution).where(
        ExternalDocumentSourceTokenAcquisitionExecution.id == execution_id,
        ExternalDocumentSourceTokenAcquisitionExecution.organization_id == organization_id,
        ExternalDocumentSourceTokenAcquisitionExecution.profile_id == profile_id,
    ))
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Token acquisition execution not found")
    return row


def _resolution(db: Session, execution: ExternalDocumentSourceTokenAcquisitionExecution) -> ExternalDocumentSourceCredentialResolutionExecution:
    row = db.scalar(select(ExternalDocumentSourceCredentialResolutionExecution).where(
        ExternalDocumentSourceCredentialResolutionExecution.id == execution.credential_resolution_execution_id,
        ExternalDocumentSourceCredentialResolutionExecution.organization_id == execution.organization_id,
        ExternalDocumentSourceCredentialResolutionExecution.profile_id == execution.profile_id,
    ))
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase I credential resolution lineage is missing")
    return row


def _active_binding(db: Session, resolution: ExternalDocumentSourceCredentialResolutionExecution):
    binding = get_external_document_source_credential_reference(
        db,
        organization_id=resolution.organization_id,
        profile_id=resolution.profile_id,
        binding_id=resolution.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("Bound credential reference is not active")
    if binding.provider_kind != resolution.provider_kind or binding.profile_hash != resolution.profile_hash or binding.locator_hash != resolution.locator_hash or binding.reference_backend != resolution.reference_backend:
        raise ExternalDocumentSourceConflictError("Token acquisition credential-reference lineage drifted")
    return binding


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceTokenAcquisitionExecution) -> None:
    if execution.status != "completed" or execution.result_status != "acquired" or execution.expiry_class not in _ALLOWED_EXPIRY_CLASSES:
        raise ExternalDocumentSourceConflictError("Token acquisition execution lifecycle is incomplete")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Token acquisition execution safety boundary drifted")

    resolution = _resolution(db, execution)
    _ensure_credential_resolution_integrity(db, resolution)
    if resolution.status != "completed" or resolution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase I credential resolution is not complete")
    _active_binding(db, resolution)

    profile = _get_profile(db, organization_id=execution.organization_id, profile_id=execution.profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != execution.profile_hash:
        raise ExternalDocumentSourceConflictError("Token acquisition source profile is not active")
    policy = _token_policy(profile.provider_kind, profile.normalized_config)
    expected_policy_hash = _endpoint_policy_hash(policy)
    if (
        execution.activation_execution_id != resolution.activation_execution_id
        or execution.authorization_id != resolution.authorization_id
        or execution.health_qualification_id != resolution.health_qualification_id
        or execution.credential_reference_binding_id != resolution.credential_reference_binding_id
        or execution.provider_kind != resolution.provider_kind
        or execution.profile_hash != resolution.profile_hash
        or execution.locator_hash != resolution.locator_hash
        or execution.reference_backend != resolution.reference_backend
        or execution.resolution_resolver_kind != resolution.resolution_resolver_kind
        or execution.credential_resolution_scope_hash != resolution.scope_hash
        or execution.credential_resolution_request_hash != resolution.request_hash
        or execution.credential_resolution_completion_hash != resolution.completion_hash
        or execution.token_flow_kind != policy.token_flow_kind
        or execution.endpoint_policy_hash != expected_policy_hash
    ):
        raise ExternalDocumentSourceConflictError("Token acquisition execution lineage drifted")
    acquirer_kind = _normalize_identifier(execution.acquirer_kind, field="Token acquirer kind")
    expected_scope = _scope_hash(
        resolution=resolution,
        token_flow_kind=policy.token_flow_kind,
        acquirer_kind=acquirer_kind,
        endpoint_policy_hash=expected_policy_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Token acquisition request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Token acquisition completion integrity failed")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Token acquisition timestamps drifted")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Token acquisition receipt lifecycle is incomplete")
    expected_rows = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior: str | None = None
    for receipt, facts in zip(rows, expected_rows, strict=True):
        sequence, status_after, occurred_at, decision_hash, performed = facts
        if (
            receipt.sequence_number != sequence or receipt.event_type != status_after or receipt.status_after != status_after
            or receipt.actor_id != execution.requested_by_id or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != execution.request_reason or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != decision_hash or receipt.prior_receipt_hash != prior
        ):
            raise ExternalDocumentSourceConflictError("Token acquisition receipt facts drifted")
        for field, expected in _base_safety(performed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Token acquisition receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Token acquisition receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_token_acquisition(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    credential_resolution_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    existing = db.scalar(select(ExternalDocumentSourceTokenAcquisitionExecution).where(
        ExternalDocumentSourceTokenAcquisitionExecution.organization_id == organization_id,
        ExternalDocumentSourceTokenAcquisitionExecution.profile_id == profile_id,
        ExternalDocumentSourceTokenAcquisitionExecution.credential_resolution_execution_id == credential_resolution_execution_id,
    ))
    if existing is not None:
        _ensure_integrity(db, existing)
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for token acquisition execution")
        return existing, "unchanged"

    key_collision = db.scalar(select(ExternalDocumentSourceTokenAcquisitionExecution).where(
        ExternalDocumentSourceTokenAcquisitionExecution.organization_id == organization_id,
        ExternalDocumentSourceTokenAcquisitionExecution.profile_id == profile_id,
        ExternalDocumentSourceTokenAcquisitionExecution.request_key == normalized_key,
    ))
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for token acquisition request_key")

    resolution = db.scalar(select(ExternalDocumentSourceCredentialResolutionExecution).where(
        ExternalDocumentSourceCredentialResolutionExecution.id == credential_resolution_execution_id,
        ExternalDocumentSourceCredentialResolutionExecution.organization_id == organization_id,
        ExternalDocumentSourceCredentialResolutionExecution.profile_id == profile_id,
    ).with_for_update())
    if resolution is None:
        raise ExternalDocumentSourceNotFoundError("Phase I credential resolution execution not found")

    existing = db.scalar(select(ExternalDocumentSourceTokenAcquisitionExecution).where(
        ExternalDocumentSourceTokenAcquisitionExecution.credential_resolution_execution_id == credential_resolution_execution_id
    ))
    if existing is not None:
        _ensure_integrity(db, existing)
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for token acquisition execution")
        return existing, "unchanged"

    _ensure_credential_resolution_integrity(db, resolution)
    if resolution.status != "completed" or resolution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase I credential resolution is not eligible for token acquisition")
    binding = _active_binding(db, resolution)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != resolution.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")

    policy = _token_policy(profile.provider_kind, profile.normalized_config)
    acquirer = _TOKEN_ACQUIRERS.get((profile.provider_kind, policy.token_flow_kind))
    if acquirer is None:
        raise ExternalDocumentSourceConflictError("Token acquirer is unavailable")
    acquirer_kind = _normalize_identifier(acquirer.acquirer_kind, field="Token acquirer kind")
    if acquirer.provider_kind != profile.provider_kind or acquirer.token_flow_kind != policy.token_flow_kind or acquirer.token_endpoint_origin != _PROVIDER_POLICIES[profile.provider_kind]["token_endpoint_origin"]:
        raise ExternalDocumentSourceConflictError("Token acquirer policy drifted")

    endpoint_policy_hash = _endpoint_policy_hash(policy)
    current = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        resolution=resolution,
        token_flow_kind=policy.token_flow_kind,
        acquirer_kind=acquirer_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution = ExternalDocumentSourceTokenAcquisitionExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        credential_resolution_execution_id=resolution.id,
        activation_execution_id=resolution.activation_execution_id,
        authorization_id=resolution.authorization_id,
        health_qualification_id=resolution.health_qualification_id,
        credential_reference_binding_id=resolution.credential_reference_binding_id,
        provider_kind=resolution.provider_kind,
        profile_hash=resolution.profile_hash,
        locator_hash=resolution.locator_hash,
        reference_backend=resolution.reference_backend,
        resolution_resolver_kind=resolution.resolution_resolver_kind,
        credential_resolution_scope_hash=resolution.scope_hash,
        credential_resolution_request_hash=resolution.request_hash,
        credential_resolution_completion_hash=resolution.completion_hash,
        token_flow_kind=policy.token_flow_kind,
        acquirer_kind=acquirer_kind,
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
    _append_receipt(db, execution=execution, event_type="requested", actor_id=requested_by_id, occurred_at=current, decision_hash=execution.request_hash)

    locator = CredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    try:
        result = acquirer.acquire(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Token acquisition failed") from None
    _validate_result(result)

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.result_status = "acquired"
    execution.expiry_class = result.expiry_class
    execution.completed_at = completed_at
    execution.token_acquisition_performed = True
    execution.oauth_token_exchanged = True
    execution.token_endpoint_network_performed = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(db, execution=execution, event_type="completed", actor_id=requested_by_id, occurred_at=completed_at, decision_hash=execution.completion_hash)
    db.flush()
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_token_acquisition_execution(db: Session, *, organization_id: UUID, profile_id: UUID, execution_id: UUID):
    execution = _get_execution(db, organization_id=organization_id, profile_id=profile_id, execution_id=execution_id)
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_token_acquisition_execution_receipts(db: Session, *, organization_id: UUID, profile_id: UUID, execution_id: UUID):
    execution = get_external_document_source_token_acquisition_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
