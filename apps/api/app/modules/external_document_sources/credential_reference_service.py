import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.connection_bootstrap_service import (
    get_external_document_source_connection_bootstrap_execution,
)
from app.modules.external_document_sources.credential_reference_models import (
    ExternalDocumentSourceCredentialReferenceBinding,
    ExternalDocumentSourceCredentialReferenceReceipt,
)
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
)


_ALLOWED_BACKENDS = {
    "aws_secrets_manager",
    "azure_key_vault",
    "gcp_secret_manager",
    "hashicorp_vault",
}
_SAFETY_FIELDS = (
    "credential_stored",
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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


def _looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    if value.startswith(("AKIA", "ASIA")) and len(value) >= 16:
        return True
    if lowered.startswith(("sk-", "ghp_", "github_pat_")) and len(value) >= 20:
        return True
    if value.startswith("eyJ") and value.count(".") >= 2:
        return True
    return False


def _normalize_locator_component(
    value: str,
    *,
    field: str,
    maximum: int,
    version: bool = False,
) -> str:
    normalized = _normalize_text(value, field=field, minimum=1, maximum=maximum)
    pattern = _VERSION if version else _IDENTIFIER
    if not pattern.fullmatch(normalized):
        raise ExternalDocumentSourceValidationError(
            f"{field} must be a non-secret identifier using only letters, numbers, dot, underscore, hyphen"
            + ("" if version else " or slash")
        )
    if _looks_like_secret(normalized):
        raise ExternalDocumentSourceValidationError(f"{field} appears to contain secret material")
    return normalized


def _normalize_backend(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_BACKENDS:
        raise ExternalDocumentSourceValidationError("Unsupported credential reference backend")
    return normalized


def _locator_hash(*, backend: str, namespace: str, name: str, version: str | None) -> str:
    return _canonical_hash(
        {
            "reference_backend": backend,
            "reference_namespace": namespace,
            "reference_name": name,
            "reference_version": version,
        }
    )


def _scope_hash(*, organization_id: UUID, profile: ExternalDocumentSourceProfile, execution, locator_hash: str, request_key: str) -> str:
    if execution.completion_hash is None or execution.authorization_terminal_hash is None:
        raise ExternalDocumentSourceConflictError("External provider bootstrap execution is incomplete")
    return _canonical_hash(
        {
            "organization_id": str(organization_id),
            "profile_id": str(profile.id),
            "provider_kind": profile.provider_kind,
            "profile_hash": profile.profile_hash,
            "bootstrap_execution_id": str(execution.id),
            "bootstrap_scope_hash": execution.scope_hash,
            "bootstrap_request_hash": execution.request_hash,
            "bootstrap_completion_hash": execution.completion_hash,
            "authorization_terminal_hash": execution.authorization_terminal_hash,
            "locator_hash": locator_hash,
            "request_key": request_key,
        }
    )


def _request_hash(binding: ExternalDocumentSourceCredentialReferenceBinding) -> str:
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "requested_by_id": str(binding.requested_by_id),
            "request_reason": binding.request_reason,
            "requested_at": _iso(binding.requested_at),
            "credential_reference_stored": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _approval_hash(binding: ExternalDocumentSourceCredentialReferenceBinding) -> str:
    if binding.approved_by_id is None or binding.approved_at is None or binding.approval_reason is None:
        raise ExternalDocumentSourceConflictError("Credential reference approval facts are incomplete")
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "request_hash": binding.request_hash,
            "approved_by_id": str(binding.approved_by_id),
            "approved_at": _iso(binding.approved_at),
            "approval_reason": binding.approval_reason,
            "status": "active",
            "credential_reference_stored": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _terminal_hash(binding: ExternalDocumentSourceCredentialReferenceBinding) -> str:
    if binding.terminal_by_id is None or binding.terminal_at is None or binding.terminal_reason is None:
        raise ExternalDocumentSourceConflictError("Credential reference terminal facts are incomplete")
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "request_hash": binding.request_hash,
            "approval_hash": binding.approval_hash,
            "status": binding.status,
            "terminal_by_id": str(binding.terminal_by_id),
            "terminal_at": _iso(binding.terminal_at),
            "terminal_reason": binding.terminal_reason,
            "credential_reference_stored": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceCredentialReferenceReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "binding_id": str(receipt.binding_id),
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
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _get_binding(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> ExternalDocumentSourceCredentialReferenceBinding:
    row = db.scalar(
        select(ExternalDocumentSourceCredentialReferenceBinding).where(
            ExternalDocumentSourceCredentialReferenceBinding.id == binding_id,
            ExternalDocumentSourceCredentialReferenceBinding.organization_id == organization_id,
            ExternalDocumentSourceCredentialReferenceBinding.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("External provider credential reference binding not found")
    return row


def _receipts(db: Session, binding: ExternalDocumentSourceCredentialReferenceBinding):
    return list(
        db.scalars(
            select(ExternalDocumentSourceCredentialReferenceReceipt)
            .where(
                ExternalDocumentSourceCredentialReferenceReceipt.organization_id == binding.organization_id,
                ExternalDocumentSourceCredentialReferenceReceipt.binding_id == binding.id,
            )
            .order_by(ExternalDocumentSourceCredentialReferenceReceipt.sequence_number.asc())
        ).all()
    )


def _lineage(db: Session, binding: ExternalDocumentSourceCredentialReferenceBinding):
    profile = get_external_document_source_profile(
        db,
        organization_id=binding.organization_id,
        profile_id=binding.profile_id,
    )
    execution = get_external_document_source_connection_bootstrap_execution(
        db,
        organization_id=binding.organization_id,
        profile_id=binding.profile_id,
        execution_id=binding.bootstrap_execution_id,
    )
    if execution.completion_hash is None or execution.authorization_terminal_hash is None:
        raise ExternalDocumentSourceConflictError("Credential reference upstream bootstrap execution is incomplete")
    if (
        binding.provider_kind != profile.provider_kind
        or binding.provider_kind != execution.provider_kind
        or binding.profile_hash != profile.profile_hash
        or binding.profile_hash != execution.profile_hash
        or binding.bootstrap_scope_hash != execution.scope_hash
        or binding.bootstrap_request_hash != execution.request_hash
        or binding.bootstrap_completion_hash != execution.completion_hash
        or binding.authorization_terminal_hash != execution.authorization_terminal_hash
    ):
        raise ExternalDocumentSourceConflictError("Credential reference upstream lineage drifted")
    return profile, execution


def _expected_events(binding: ExternalDocumentSourceCredentialReferenceBinding) -> list[str]:
    if binding.status == "pending_second_approval":
        return ["requested"]
    if binding.status == "active":
        return ["requested", "approved"]
    if binding.status == "rejected":
        return ["requested", "rejected"]
    if binding.status == "disabled":
        return ["requested", "approved", "disabled"]
    raise ExternalDocumentSourceConflictError("Credential reference binding status is invalid")


def _expected_receipt_facts(binding: ExternalDocumentSourceCredentialReferenceBinding, event_type: str):
    if event_type == "requested":
        return binding.requested_by_id, binding.requested_at, binding.request_reason, "pending_second_approval", binding.request_hash
    if event_type == "approved":
        return binding.approved_by_id, binding.approved_at, binding.approval_reason, "active", binding.approval_hash
    if event_type in {"rejected", "disabled"}:
        return binding.terminal_by_id, binding.terminal_at, binding.terminal_reason, binding.status, binding.terminal_hash
    raise ExternalDocumentSourceConflictError("Credential reference receipt event is invalid")


def _ensure_integrity(db: Session, binding: ExternalDocumentSourceCredentialReferenceBinding) -> None:
    profile, execution = _lineage(db, binding)
    expected_locator = _locator_hash(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    if binding.locator_hash != expected_locator:
        raise ExternalDocumentSourceConflictError("Credential reference locator integrity failed")
    expected_scope = _scope_hash(
        organization_id=binding.organization_id,
        profile=profile,
        execution=execution,
        locator_hash=binding.locator_hash,
        request_key=binding.request_key,
    )
    if binding.scope_hash != expected_scope or binding.request_hash != _request_hash(binding):
        raise ExternalDocumentSourceConflictError("Credential reference request integrity failed")
    if not binding.credential_reference_stored or any(bool(getattr(binding, field)) for field in _SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("Credential reference safety boundary drifted")
    if binding.approval_hash is not None and binding.approval_hash != _approval_hash(binding):
        raise ExternalDocumentSourceConflictError("Credential reference approval integrity failed")
    if binding.status in {"active", "disabled"} and binding.requested_by_id == binding.approved_by_id:
        raise ExternalDocumentSourceConflictError("Credential reference four-eyes boundary drifted")
    if binding.terminal_hash is not None and binding.terminal_hash != _terminal_hash(binding):
        raise ExternalDocumentSourceConflictError("Credential reference terminal integrity failed")

    rows = _receipts(db, binding)
    events = _expected_events(binding)
    if len(rows) != len(events) or [row.event_type for row in rows] != events:
        raise ExternalDocumentSourceConflictError("Credential reference receipt lifecycle is incomplete")
    prior: str | None = None
    for sequence_number, receipt in enumerate(rows, start=1):
        if receipt.sequence_number != sequence_number or receipt.prior_receipt_hash != prior:
            raise ExternalDocumentSourceConflictError("Credential reference receipt chain linkage failed")
        if receipt.scope_hash != binding.scope_hash or not receipt.credential_reference_stored:
            raise ExternalDocumentSourceConflictError("Credential reference receipt scope drifted")
        if any(bool(getattr(receipt, field)) for field in _SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("Credential reference receipt safety boundary drifted")
        expected_actor, expected_time, expected_reason, expected_status, expected_decision = _expected_receipt_facts(
            binding, receipt.event_type
        )
        if expected_actor is None or expected_time is None or expected_reason is None or expected_decision is None:
            raise ExternalDocumentSourceConflictError("Credential reference receipt facts are incomplete")
        if (
            receipt.actor_id != expected_actor
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != expected_reason
            or receipt.status_after != expected_status
            or receipt.decision_hash != expected_decision
        ):
            raise ExternalDocumentSourceConflictError("Credential reference receipt facts drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Credential reference receipt integrity failed")
        prior = receipt.receipt_hash


def _require_active_profile(profile: ExternalDocumentSourceProfile) -> None:
    if profile.status != "active":
        raise ExternalDocumentSourceConflictError("Bound external document source profile is not active")


def _append_receipt(
    db: Session,
    *,
    binding: ExternalDocumentSourceCredentialReferenceBinding,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    decision_hash: str,
) -> None:
    rows = _receipts(db, binding)
    receipt = ExternalDocumentSourceCredentialReferenceReceipt(
        organization_id=binding.organization_id,
        binding_id=binding.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=binding.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        scope_hash=binding.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        credential_reference_stored=True,
        **{field: False for field in _SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def request_external_document_source_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    bootstrap_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    reference_backend: str,
    reference_namespace: str,
    reference_name: str,
    reference_version: str | None,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    backend = _normalize_backend(reference_backend)
    namespace = _normalize_locator_component(reference_namespace, field="reference_namespace", maximum=128)
    name = _normalize_locator_component(reference_name, field="reference_name", maximum=128)
    version = (
        _normalize_locator_component(reference_version, field="reference_version", maximum=64, version=True)
        if reference_version is not None
        else None
    )
    locator_hash = _locator_hash(backend=backend, namespace=namespace, name=name, version=version)

    execution = get_external_document_source_connection_bootstrap_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=bootstrap_execution_id,
    )
    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    _require_active_profile(profile)
    scope_hash = _scope_hash(
        organization_id=organization_id,
        profile=profile,
        execution=execution,
        locator_hash=locator_hash,
        request_key=normalized_key,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceCredentialReferenceBinding).where(
            ExternalDocumentSourceCredentialReferenceBinding.bootstrap_execution_id == bootstrap_execution_id
        )
    )
    if existing is not None:
        if existing.organization_id != organization_id or existing.profile_id != profile_id:
            raise ExternalDocumentSourceNotFoundError("External provider bootstrap execution not found")
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
            or existing.reference_backend != backend
            or existing.reference_namespace != namespace
            or existing.reference_name != name
            or existing.reference_version != version
            or existing.locator_hash != locator_hash
            or existing.scope_hash != scope_hash
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for external provider credential reference")
        return existing, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceCredentialReferenceBinding).where(
            ExternalDocumentSourceCredentialReferenceBinding.organization_id == organization_id,
            ExternalDocumentSourceCredentialReferenceBinding.profile_id == profile_id,
            ExternalDocumentSourceCredentialReferenceBinding.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for credential reference request_key")

    current = _aware(now or _utc_now())
    binding = ExternalDocumentSourceCredentialReferenceBinding(
        organization_id=organization_id,
        profile_id=profile_id,
        bootstrap_execution_id=execution.id,
        provider_kind=execution.provider_kind,
        profile_hash=execution.profile_hash,
        bootstrap_scope_hash=execution.scope_hash,
        bootstrap_request_hash=execution.request_hash,
        bootstrap_completion_hash=execution.completion_hash,
        authorization_terminal_hash=execution.authorization_terminal_hash,
        reference_backend=backend,
        reference_namespace=namespace,
        reference_name=name,
        reference_version=version,
        locator_hash=locator_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        credential_reference_stored=True,
        **{field: False for field in _SAFETY_FIELDS},
    )
    db.add(binding)
    db.flush()
    binding.request_hash = _request_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=binding.request_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "requested"


def approve_external_document_source_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    approved_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    binding = _get_binding(db, organization_id=organization_id, profile_id=profile_id, binding_id=binding_id)
    _ensure_integrity(db, binding)
    profile, _ = _lineage(db, binding)
    _require_active_profile(profile)
    if binding.status == "active":
        if binding.approved_by_id == approved_by_id and binding.approval_reason == reason:
            return binding, "unchanged"
        raise ExternalDocumentSourceConflictError("Credential reference binding is already approved")
    if binding.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError("Credential reference binding is not pending approval")
    if binding.requested_by_id == approved_by_id:
        raise ExternalDocumentSourceConflictError("Independent second approval is required")

    current = _aware(now or _utc_now())
    binding.status = "active"
    binding.approved_by_id = approved_by_id
    binding.approved_at = current
    binding.approval_reason = reason
    binding.approval_hash = _approval_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="approved",
        actor_id=approved_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=binding.approval_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "approved"


def reject_external_document_source_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    binding = _get_binding(db, organization_id=organization_id, profile_id=profile_id, binding_id=binding_id)
    _ensure_integrity(db, binding)
    if binding.status == "rejected":
        if binding.terminal_by_id == rejected_by_id and binding.terminal_reason == reason:
            return binding, "unchanged"
        raise ExternalDocumentSourceConflictError("Credential reference binding is already rejected")
    if binding.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError("Credential reference binding is not pending rejection")

    current = _aware(now or _utc_now())
    binding.status = "rejected"
    binding.terminal_by_id = rejected_by_id
    binding.terminal_at = current
    binding.terminal_reason = reason
    binding.terminal_hash = _terminal_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="rejected",
        actor_id=rejected_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=binding.terminal_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "rejected"


def disable_external_document_source_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    disabled_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    reason = _normalize_text(decision_reason, field="reason", minimum=8, maximum=2000)
    binding = _get_binding(db, organization_id=organization_id, profile_id=profile_id, binding_id=binding_id)
    _ensure_integrity(db, binding)
    if binding.status == "disabled":
        if binding.terminal_by_id == disabled_by_id and binding.terminal_reason == reason:
            return binding, "unchanged"
        raise ExternalDocumentSourceConflictError("Credential reference binding is already disabled")
    if binding.status != "active":
        raise ExternalDocumentSourceConflictError("Only an active credential reference binding may be disabled")

    current = _aware(now or _utc_now())
    binding.status = "disabled"
    binding.terminal_by_id = disabled_by_id
    binding.terminal_at = current
    binding.terminal_reason = reason
    binding.terminal_hash = _terminal_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="disabled",
        actor_id=disabled_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=binding.terminal_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "disabled"


def get_external_document_source_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
):
    binding = _get_binding(db, organization_id=organization_id, profile_id=profile_id, binding_id=binding_id)
    _ensure_integrity(db, binding)
    profile, _ = _lineage(db, binding)
    if binding.status in {"pending_second_approval", "active"}:
        _require_active_profile(profile)
    return binding


def list_external_document_source_credential_reference_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
):
    binding = get_external_document_source_credential_reference(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    return _receipts(db, binding)
