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

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
    normalize_provider_config,
)
from app.modules.external_document_sources.sftp_credential_health_models import (
    ExternalDocumentSourceSftpCredentialHealthQualification,
)
from app.modules.external_document_sources.sftp_credential_health_service import (
    _ensure_integrity as _ensure_health_integrity,
)
from app.modules.external_document_sources.sftp_credential_reference_models import (
    ExternalDocumentSourceSftpCredentialReferenceBinding,
)
from app.modules.external_document_sources.sftp_credential_reference_service import (
    get_external_document_source_sftp_credential_reference,
)
from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
)
from app.modules.external_document_sources.sftp_handshake_execution_service import (
    _ensure_integrity as _ensure_handshake_execution_integrity,
)
from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
    ExternalDocumentSourceSftpSessionActivationReceipt,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    _ensure_integrity as _ensure_transport_verification_integrity,
)


_SAFE_ADAPTER_KIND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_AUTH_KINDS = frozenset({"password", "private_key"})
_ALLOWED_AUTH_METHODS = frozenset({"password", "public_key"})
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_ALLOWED_FAILURE_CODES = frozenset({
    "credential_resolution_failed",
    "credential_unavailable",
    "authentication_failed",
    "authentication_timeout",
    "unsupported_authentication_method",
    "host_key_revalidation_failed",
    "sftp_subsystem_activation_failed",
    "destination_policy_violation",
    "adapter_boundary_violation",
})
_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "remote_list_performed",
    "remote_stat_performed",
    "remote_read_performed",
    "remote_write_performed",
    "remote_rename_performed",
    "remote_delete_performed",
    "command_executed",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


@dataclass(frozen=True)
class SftpSessionActivationRequest:
    hostname: str
    port: int
    pinned_host_key_fingerprint: str
    authentication_kind: str
    reference_backend: str
    reference_namespace: str
    reference_name: str
    reference_version: str | None
    connect_timeout_seconds: int = 5
    authentication_timeout_seconds: int = 5
    subsystem_timeout_seconds: int = 5
    max_connection_attempts: int = 1
    max_authentication_attempts: int = 1
    allow_private_destinations: bool = False
    allow_redirects: bool = False
    allow_proxy_retargeting: bool = False
    read_only_intent: bool = True


@dataclass(frozen=True)
class SftpSessionActivationResult:
    failure_code: str | None = None
    authentication_method: str | None = None
    latency_class: str | None = None
    secret_resolution_performed: bool = False
    provider_network_performed: bool = False
    ssh_transport_performed: bool = False
    host_key_verification_performed: bool = False
    host_key_verified: bool = False
    authentication_performed: bool = False
    authentication_succeeded: bool = False
    sftp_session_opened: bool = False
    sftp_session_closed: bool = False
    credential_persisted: bool = False
    remote_operation_performed: bool = False
    command_executed: bool = False


class SftpSessionActivationAdapter(Protocol):
    adapter_kind: str

    def activate(self, request: SftpSessionActivationRequest) -> SftpSessionActivationResult: ...


_ACTIVATION_ADAPTER: SftpSessionActivationAdapter | None = None


def register_external_document_source_sftp_session_activation_adapter(adapter: SftpSessionActivationAdapter) -> None:
    global _ACTIVATION_ADAPTER
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_ADAPTER_KIND.fullmatch(adapter_kind):
        raise ValueError("SFTP session activation adapter kind is invalid")
    _ACTIVATION_ADAPTER = adapter


def clear_external_document_source_sftp_session_activation_adapter() -> None:
    global _ACTIVATION_ADAPTER
    _ACTIVATION_ADAPTER = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _normalize_adapter_kind(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_ADAPTER_KIND.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError("SFTP session activation adapter kind is invalid")
    return normalized


def _scope_hash(*, verification, execution, binding, adapter_kind: str, request_key: str) -> str:
    return _canonical_hash({
        "organization_id": str(verification.organization_id),
        "profile_id": str(verification.profile_id),
        "transport_verification_id": str(verification.id),
        "transport_verification_scope_hash": verification.scope_hash,
        "transport_verification_request_hash": verification.request_hash,
        "transport_verification_result_hash": verification.result_hash,
        "handshake_execution_id": str(execution.id),
        "handshake_execution_completion_hash": execution.completion_hash,
        "health_qualification_id": str(execution.health_qualification_id),
        "credential_reference_binding_id": str(binding.id),
        "locator_hash": binding.locator_hash,
        "authentication_kind": binding.authentication_kind,
        "reference_backend": binding.reference_backend,
        "destination_hostname": verification.destination_hostname,
        "destination_port": verification.destination_port,
        "pinned_host_key_fingerprint": verification.pinned_host_key_fingerprint,
        "adapter_kind": adapter_kind,
        "request_key": request_key,
        "activation_limit": 1,
    })


def _request_hash(row: ExternalDocumentSourceSftpSessionActivation) -> str:
    return _canonical_hash({
        "activation_id": str(row.id),
        "scope_hash": row.scope_hash,
        "requested_by_id": str(row.requested_by_id),
        "request_reason": row.request_reason,
        "requested_at": _iso(row.requested_at),
        "credential_reference_stored": True,
        "secret_resolution_performed": False,
        "provider_network_performed": False,
        "ssh_transport_performed": False,
        "host_key_verification_performed": False,
        "host_key_verified": False,
        "authentication_performed": False,
        "authentication_succeeded": False,
        "sftp_session_opened": False,
        "sftp_session_closed": False,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    })


def _result_hash(row: ExternalDocumentSourceSftpSessionActivation) -> str:
    return _canonical_hash({
        "activation_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "checked_at": _iso(row.checked_at),
        "result_status": row.result_status,
        "failure_code": row.failure_code,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "credential_reference_stored": True,
        "secret_resolution_performed": row.secret_resolution_performed,
        "provider_network_performed": row.provider_network_performed,
        "ssh_transport_performed": row.ssh_transport_performed,
        "host_key_verification_performed": row.host_key_verification_performed,
        "host_key_verified": row.host_key_verified,
        "authentication_performed": row.authentication_performed,
        "authentication_succeeded": row.authentication_succeeded,
        "sftp_session_opened": row.sftp_session_opened,
        "sftp_session_closed": row.sftp_session_closed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    })


def _receipt_hash(receipt: ExternalDocumentSourceSftpSessionActivationReceipt) -> str:
    return _canonical_hash({
        "organization_id": str(receipt.organization_id),
        "activation_id": str(receipt.activation_id),
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
        "secret_resolution_performed": receipt.secret_resolution_performed,
        "provider_network_performed": receipt.provider_network_performed,
        "ssh_transport_performed": receipt.ssh_transport_performed,
        "host_key_verification_performed": receipt.host_key_verification_performed,
        "host_key_verified": receipt.host_key_verified,
        "authentication_performed": receipt.authentication_performed,
        "authentication_succeeded": receipt.authentication_succeeded,
        "sftp_session_opened": receipt.sftp_session_opened,
        "sftp_session_closed": receipt.sftp_session_closed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    })


def _receipts(db: Session, row: ExternalDocumentSourceSftpSessionActivation):
    return list(db.scalars(
        select(ExternalDocumentSourceSftpSessionActivationReceipt)
        .where(
            ExternalDocumentSourceSftpSessionActivationReceipt.organization_id == row.organization_id,
            ExternalDocumentSourceSftpSessionActivationReceipt.activation_id == row.id,
        )
        .order_by(ExternalDocumentSourceSftpSessionActivationReceipt.sequence_number.asc())
    ).all())


def _append_receipt(db: Session, *, row, event_type: str, occurred_at: datetime, status_after: str, decision_hash: str) -> None:
    receipts = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpSessionActivationReceipt(
        organization_id=row.organization_id,
        activation_id=row.id,
        sequence_number=len(receipts) + 1,
        event_type=event_type,
        status_after=status_after,
        actor_id=row.requested_by_id,
        occurred_at=occurred_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=receipts[-1].receipt_hash if receipts else None,
        credential_reference_stored=True,
        secret_resolution_performed=(row.secret_resolution_performed if event_type == "completed" else False),
        provider_network_performed=(row.provider_network_performed if event_type == "completed" else False),
        ssh_transport_performed=(row.ssh_transport_performed if event_type == "completed" else False),
        host_key_verification_performed=(row.host_key_verification_performed if event_type == "completed" else False),
        host_key_verified=(row.host_key_verified if event_type == "completed" else False),
        authentication_performed=(row.authentication_performed if event_type == "completed" else False),
        authentication_succeeded=(row.authentication_succeeded if event_type == "completed" else False),
        sftp_session_opened=(row.sftp_session_opened if event_type == "completed" else False),
        sftp_session_closed=(row.sftp_session_closed if event_type == "completed" else False),
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _load_verified_lineage(db: Session, *, organization_id: UUID, profile_id: UUID, verification_id: UUID, for_update: bool):
    stmt = select(ExternalDocumentSourceSftpTransportVerification).where(
        ExternalDocumentSourceSftpTransportVerification.id == verification_id,
        ExternalDocumentSourceSftpTransportVerification.organization_id == organization_id,
        ExternalDocumentSourceSftpTransportVerification.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    verification = db.scalar(stmt)
    if verification is None:
        raise ExternalDocumentSourceNotFoundError("SFTP transport verification not found")
    _ensure_transport_verification_integrity(db, verification)
    if verification.result_status != "verified" or not verification.host_key_verified:
        raise ExternalDocumentSourceConflictError("SFTP session activation requires an exact verified Phase 17.6-F result")

    execution = db.get(ExternalDocumentSourceSftpHandshakeExecution, verification.handshake_execution_id)
    if execution is None:
        raise ExternalDocumentSourceConflictError("SFTP handshake execution lineage is missing")
    _ensure_handshake_execution_integrity(db, execution)

    health = db.get(ExternalDocumentSourceSftpCredentialHealthQualification, execution.health_qualification_id)
    if health is None:
        raise ExternalDocumentSourceConflictError("SFTP credential health lineage is missing")
    _ensure_health_integrity(db, health)
    if health.result_status != "qualified":
        raise ExternalDocumentSourceConflictError("SFTP credential health is not qualified")

    binding = get_external_document_source_sftp_credential_reference(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=execution.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("SFTP credential reference is not active")

    if (
        execution.health_qualification_id != health.id
        or execution.credential_reference_binding_id != binding.id
        or execution.locator_hash != binding.locator_hash
        or execution.authentication_kind != binding.authentication_kind
        or execution.reference_backend != binding.reference_backend
        or health.credential_reference_binding_id != binding.id
        or health.locator_hash != binding.locator_hash
    ):
        raise ExternalDocumentSourceConflictError("SFTP session activation credential lineage drifted")

    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    normalized = normalize_provider_config("sftp", profile.normalized_config)
    if (
        profile.status != "active"
        or profile.provider_kind != "sftp"
        or normalized != profile.normalized_config
        or normalized["access_mode"] != "read_only"
        or profile.profile_hash != verification.profile_hash
        or verification.destination_hostname != normalized["hostname"]
        or verification.destination_port != normalized["port"]
        or verification.pinned_host_key_fingerprint != normalized["host_key_fingerprint"]
    ):
        raise ExternalDocumentSourceConflictError("SFTP session activation profile/destination lineage drifted")

    return verification, execution, health, binding


def _validated_result(result: SftpSessionActivationResult, *, expected_auth_kind: str) -> dict:
    if not isinstance(result, SftpSessionActivationResult):
        return {"result_status": "failed", "failure_code": "invalid_adapter_result", "authentication_method": None, "latency_class": None}

    if result.credential_persisted or result.remote_operation_performed or result.command_executed:
        raise ExternalDocumentSourceConflictError("SFTP session activation adapter violated the no-remote-operation boundary")

    if result.failure_code is not None:
        failure_code = result.failure_code if result.failure_code in _ALLOWED_FAILURE_CODES else "invalid_adapter_result"
        return {
            "result_status": "failed",
            "failure_code": failure_code,
            "authentication_method": result.authentication_method if result.authentication_method in _ALLOWED_AUTH_METHODS else None,
            "latency_class": result.latency_class if result.latency_class in _ALLOWED_LATENCY_CLASSES else None,
            "secret_resolution_performed": bool(result.secret_resolution_performed),
            "provider_network_performed": bool(result.provider_network_performed),
            "ssh_transport_performed": bool(result.ssh_transport_performed),
            "host_key_verification_performed": bool(result.host_key_verification_performed),
            "host_key_verified": bool(result.host_key_verified),
            "authentication_performed": bool(result.authentication_performed),
            "authentication_succeeded": bool(result.authentication_succeeded),
            "sftp_session_opened": bool(result.sftp_session_opened),
            "sftp_session_closed": bool(result.sftp_session_closed),
        }

    expected_method = "password" if expected_auth_kind == "password" else "public_key"
    if (
        result.authentication_method != expected_method
        or result.latency_class not in _ALLOWED_LATENCY_CLASSES
        or not result.secret_resolution_performed
        or not result.provider_network_performed
        or not result.ssh_transport_performed
        or not result.host_key_verification_performed
        or not result.host_key_verified
        or not result.authentication_performed
        or not result.authentication_succeeded
        or not result.sftp_session_opened
        or not result.sftp_session_closed
    ):
        return {
            "result_status": "failed",
            "failure_code": "invalid_adapter_result",
            "authentication_method": result.authentication_method if result.authentication_method in _ALLOWED_AUTH_METHODS else None,
            "latency_class": result.latency_class if result.latency_class in _ALLOWED_LATENCY_CLASSES else None,
            "secret_resolution_performed": bool(result.secret_resolution_performed),
            "provider_network_performed": bool(result.provider_network_performed),
            "ssh_transport_performed": bool(result.ssh_transport_performed),
            "host_key_verification_performed": bool(result.host_key_verification_performed),
            "host_key_verified": bool(result.host_key_verified),
            "authentication_performed": bool(result.authentication_performed),
            "authentication_succeeded": bool(result.authentication_succeeded),
            "sftp_session_opened": bool(result.sftp_session_opened),
            "sftp_session_closed": bool(result.sftp_session_closed),
        }
    return {
        "result_status": "activated",
        "failure_code": None,
        "authentication_method": expected_method,
        "latency_class": result.latency_class,
        "secret_resolution_performed": True,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": True,
        "authentication_performed": True,
        "authentication_succeeded": True,
        "sftp_session_opened": True,
        "sftp_session_closed": True,
    }


def _ensure_integrity(db: Session, row: ExternalDocumentSourceSftpSessionActivation) -> None:
    verification, execution, _health, binding = _load_verified_lineage(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        verification_id=row.transport_verification_id,
        for_update=False,
    )
    expected_scope = _scope_hash(
        verification=verification,
        execution=execution,
        binding=binding,
        adapter_kind=row.adapter_kind,
        request_key=row.request_key,
    )
    if row.scope_hash != expected_scope or row.request_hash != _request_hash(row) or row.result_hash != _result_hash(row):
        raise ExternalDocumentSourceConflictError("SFTP session activation integrity failed")
    if row.health_qualification_id != execution.health_qualification_id or row.credential_reference_binding_id != binding.id:
        raise ExternalDocumentSourceConflictError("SFTP session activation lineage drifted")
    if row.result_status == "activated":
        if row.failure_code is not None or not all((
            row.secret_resolution_performed,
            row.provider_network_performed,
            row.ssh_transport_performed,
            row.host_key_verification_performed,
            row.host_key_verified,
            row.authentication_performed,
            row.authentication_succeeded,
            row.sftp_session_opened,
            row.sftp_session_closed,
        )):
            raise ExternalDocumentSourceConflictError("SFTP session activation success facts drifted")
    elif row.result_status == "failed":
        if row.failure_code is None:
            raise ExternalDocumentSourceConflictError("SFTP session activation failure facts drifted")
    else:
        raise ExternalDocumentSourceConflictError("SFTP session activation result status is invalid")
    if row.credential_stored or any(bool(getattr(row, field)) for field in _FALSE_SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("SFTP session activation safety boundary drifted")
    receipts = _receipts(db, row)
    if len(receipts) != 2 or [r.event_type for r in receipts] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("SFTP session activation receipt lifecycle is incomplete")
    prior = None
    expected = [
        (1, "requested", row.requested_at, "requested", row.request_hash),
        (2, "completed", row.checked_at, row.result_status, row.result_hash),
    ]
    for receipt, facts in zip(receipts, expected, strict=True):
        seq, event, at, status_after, decision_hash = facts
        if (
            receipt.sequence_number != seq
            or receipt.event_type != event
            or receipt.actor_id != row.requested_by_id
            or _aware(receipt.occurred_at) != _aware(at)
            or receipt.reason != row.request_reason
            or receipt.status_after != status_after
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError("SFTP session activation receipt integrity failed")
        prior = receipt.receipt_hash


def activate_external_document_source_sftp_session(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    transport_verification_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    verification, execution, _health, binding = _load_verified_lineage(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        verification_id=transport_verification_id,
        for_update=True,
    )

    existing = db.scalar(select(ExternalDocumentSourceSftpSessionActivation).where(
        ExternalDocumentSourceSftpSessionActivation.transport_verification_id == transport_verification_id
    ))
    if existing is not None:
        if existing.organization_id != organization_id or existing.profile_id != profile_id:
            raise ExternalDocumentSourceNotFoundError("SFTP transport verification not found")
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP session activation")
        return existing, "unchanged"

    collision = db.scalar(select(ExternalDocumentSourceSftpSessionActivation).where(
        ExternalDocumentSourceSftpSessionActivation.organization_id == organization_id,
        ExternalDocumentSourceSftpSessionActivation.profile_id == profile_id,
        ExternalDocumentSourceSftpSessionActivation.request_key == normalized_key,
    ))
    if collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP session activation request_key")

    adapter = _ACTIVATION_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError("SFTP session activation adapter is unavailable")
    adapter_kind = _normalize_adapter_kind(adapter.adapter_kind)

    requested_at = _aware(now or _utc_now())
    request = SftpSessionActivationRequest(
        hostname=verification.destination_hostname,
        port=verification.destination_port,
        pinned_host_key_fingerprint=verification.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
    )
    try:
        adapter_result = adapter.activate(request)
    except Exception:
        adapter_result = SftpSessionActivationResult(
            failure_code="adapter_error",
            secret_resolution_performed=True,
        )

    if isinstance(adapter_result, SftpSessionActivationResult) and adapter_result.failure_code == "adapter_error":
        outcome = {
            "result_status": "failed",
            "failure_code": "adapter_error",
            "authentication_method": None,
            "latency_class": None,
            "secret_resolution_performed": bool(adapter_result.secret_resolution_performed),
            "provider_network_performed": bool(adapter_result.provider_network_performed),
            "ssh_transport_performed": bool(adapter_result.ssh_transport_performed),
            "host_key_verification_performed": bool(adapter_result.host_key_verification_performed),
            "host_key_verified": bool(adapter_result.host_key_verified),
            "authentication_performed": bool(adapter_result.authentication_performed),
            "authentication_succeeded": bool(adapter_result.authentication_succeeded),
            "sftp_session_opened": bool(adapter_result.sftp_session_opened),
            "sftp_session_closed": bool(adapter_result.sftp_session_closed),
        }
    else:
        outcome = _validated_result(adapter_result, expected_auth_kind=binding.authentication_kind)

    checked_at = max(requested_at, _utc_now())
    scope_hash = _scope_hash(
        verification=verification,
        execution=execution,
        binding=binding,
        adapter_kind=adapter_kind,
        request_key=normalized_key,
    )
    row = ExternalDocumentSourceSftpSessionActivation(
        organization_id=organization_id,
        profile_id=profile_id,
        transport_verification_id=verification.id,
        health_qualification_id=execution.health_qualification_id,
        credential_reference_binding_id=binding.id,
        provider_kind="sftp",
        profile_hash=verification.profile_hash,
        transport_verification_scope_hash=verification.scope_hash,
        transport_verification_request_hash=verification.request_hash,
        transport_verification_result_hash=verification.result_hash,
        locator_hash=binding.locator_hash,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        destination_hostname=verification.destination_hostname,
        destination_port=verification.destination_port,
        pinned_host_key_fingerprint=verification.pinned_host_key_fingerprint,
        adapter_kind=adapter_kind,
        activation_limit=1,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        checked_at=checked_at,
        result_status=outcome["result_status"],
        failure_code=outcome["failure_code"],
        authentication_method=outcome["authentication_method"],
        latency_class=outcome["latency_class"],
        result_hash="0" * 64,
        credential_reference_stored=True,
        secret_resolution_performed=outcome.get("secret_resolution_performed", False),
        credential_stored=False,
        provider_network_performed=outcome.get("provider_network_performed", False),
        ssh_transport_performed=outcome.get("ssh_transport_performed", False),
        host_key_verification_performed=outcome.get("host_key_verification_performed", False),
        host_key_verified=outcome.get("host_key_verified", False),
        authentication_performed=outcome.get("authentication_performed", False),
        authentication_succeeded=outcome.get("authentication_succeeded", False),
        sftp_session_opened=outcome.get("sftp_session_opened", False),
        sftp_session_closed=outcome.get("sftp_session_closed", False),
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    db.add(row)
    db.flush()
    row.request_hash = _request_hash(row)
    row.result_hash = _result_hash(row)
    _append_receipt(db, row=row, event_type="requested", occurred_at=requested_at, status_after="requested", decision_hash=row.request_hash)
    _append_receipt(db, row=row, event_type="completed", occurred_at=checked_at, status_after=row.result_status, decision_hash=row.result_hash)
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_session_activation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    activation_id: UUID,
):
    row = db.scalar(select(ExternalDocumentSourceSftpSessionActivation).where(
        ExternalDocumentSourceSftpSessionActivation.id == activation_id,
        ExternalDocumentSourceSftpSessionActivation.organization_id == organization_id,
        ExternalDocumentSourceSftpSessionActivation.profile_id == profile_id,
    ))
    if row is None:
        raise ExternalDocumentSourceNotFoundError("SFTP session activation not found")
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_session_activation_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    activation_id: UUID,
):
    row = get_external_document_source_sftp_session_activation(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        activation_id=activation_id,
    )
    return _receipts(db, row)
