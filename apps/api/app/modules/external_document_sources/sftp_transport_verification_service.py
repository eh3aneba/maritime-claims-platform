from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
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
from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
)
from app.modules.external_document_sources.sftp_handshake_execution_service import (
    _ensure_integrity as _ensure_handshake_execution_integrity,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
    ExternalDocumentSourceSftpTransportVerificationReceipt,
)


_OPENSSH_SHA256 = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
_SAFE_ADAPTER_KIND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_HOST_KEY_ALGORITHMS = frozenset(
    {
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "rsa-sha2-256",
        "rsa-sha2-512",
    }
)
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_ADAPTER_FAILURE_CODES = frozenset(
    {
        "destination_policy_violation",
        "dns_resolution_failed",
        "connection_timeout",
        "connection_refused",
        "network_unavailable",
        "ssh_negotiation_failed",
    }
)
_FALSE_SAFETY_FIELDS = (
    "secret_resolution_performed",
    "credential_stored",
    "authentication_performed",
    "sftp_session_opened",
    "remote_list_performed",
    "remote_read_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


@dataclass(frozen=True)
class SftpTransportHostKeyProbeRequest:
    hostname: str
    port: int
    connect_timeout_seconds: int = 5
    handshake_timeout_seconds: int = 5
    max_connection_attempts: int = 1
    allow_private_destinations: bool = False
    allow_redirects: bool = False
    allow_proxy_retargeting: bool = False
    pin_policy_checked_address: bool = True


@dataclass(frozen=True)
class SftpTransportHostKeyProbeResult:
    observed_host_key_fingerprint: str | None = None
    host_key_algorithm: str | None = None
    latency_class: str | None = None
    failure_code: str | None = None
    destination_policy_enforced: bool = True
    dns_resolution_performed: bool = False
    provider_network_performed: bool = False
    ssh_transport_performed: bool = False
    authentication_performed: bool = False
    sftp_session_opened: bool = False
    remote_operation_performed: bool = False


class SftpTransportHostKeyAdapter(Protocol):
    adapter_kind: str

    def probe(
        self,
        request: SftpTransportHostKeyProbeRequest,
    ) -> SftpTransportHostKeyProbeResult: ...


_TRANSPORT_ADAPTER: SftpTransportHostKeyAdapter | None = None


def register_external_document_source_sftp_transport_adapter(
    adapter: SftpTransportHostKeyAdapter,
) -> None:
    global _TRANSPORT_ADAPTER
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_ADAPTER_KIND.fullmatch(
        adapter_kind
    ):
        raise ValueError("SFTP transport adapter kind is invalid")
    _TRANSPORT_ADAPTER = adapter


def clear_external_document_source_sftp_transport_adapter() -> None:
    global _TRANSPORT_ADAPTER
    _TRANSPORT_ADAPTER = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(
    value: str,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    return normalized


def _normalize_adapter_kind(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_ADAPTER_KIND.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport adapter kind is invalid"
        )
    return normalized


def _is_literal_ip(hostname: str) -> bool:
    try:
        ip_address(hostname)
    except ValueError:
        return False
    return True


def _literal_destination_denied(hostname: str) -> bool:
    try:
        address = ip_address(hostname)
    except ValueError:
        return False
    return any(
        (
            address.is_loopback,
            address.is_unspecified,
            address.is_multicast,
            address.is_link_local,
            address.is_private,
            address.is_reserved,
        )
    )


def _scope_hash(
    *,
    execution: ExternalDocumentSourceSftpHandshakeExecution,
    destination_hostname: str,
    destination_port: int,
    pinned_host_key_fingerprint: str,
    adapter_kind: str,
    request_key: str,
) -> str:
    if execution.completion_hash is None or execution.authorization_terminal_hash is None:
        raise ExternalDocumentSourceConflictError(
            "Completed SFTP handshake execution lineage is incomplete"
        )
    return _canonical_hash(
        {
            "organization_id": str(execution.organization_id),
            "profile_id": str(execution.profile_id),
            "handshake_execution_id": str(execution.id),
            "provider_kind": execution.provider_kind,
            "profile_hash": execution.profile_hash,
            "handshake_execution_scope_hash": execution.scope_hash,
            "handshake_execution_request_hash": execution.request_hash,
            "handshake_execution_completion_hash": execution.completion_hash,
            "authorization_terminal_hash": execution.authorization_terminal_hash,
            "destination_hostname": destination_hostname,
            "destination_port": destination_port,
            "pinned_host_key_fingerprint": pinned_host_key_fingerprint,
            "adapter_kind": adapter_kind,
            "request_key": request_key,
            "verification_limit": 1,
        }
    )


def _request_hash(row: ExternalDocumentSourceSftpTransportVerification) -> str:
    return _canonical_hash(
        {
            "verification_id": str(row.id),
            "scope_hash": row.scope_hash,
            "requested_by_id": str(row.requested_by_id),
            "request_reason": row.request_reason,
            "requested_at": _iso(row.requested_at),
            "credential_reference_stored": True,
            "provider_network_performed": False,
            "ssh_transport_performed": False,
            "host_key_verification_performed": False,
            "host_key_verified": False,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _result_hash(row: ExternalDocumentSourceSftpTransportVerification) -> str:
    return _canonical_hash(
        {
            "verification_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "checked_at": _iso(row.checked_at),
            "result_status": row.result_status,
            "failure_code": row.failure_code,
            "host_key_algorithm": row.host_key_algorithm,
            "latency_class": row.latency_class,
            "credential_reference_stored": True,
            "provider_network_performed": row.provider_network_performed,
            "ssh_transport_performed": row.ssh_transport_performed,
            "host_key_verification_performed": row.host_key_verification_performed,
            "host_key_verified": row.host_key_verified,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpTransportVerificationReceipt,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "verification_id": str(receipt.verification_id),
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
            "provider_network_performed": receipt.provider_network_performed,
            "ssh_transport_performed": receipt.ssh_transport_performed,
            "host_key_verification_performed": receipt.host_key_verification_performed,
            "host_key_verified": receipt.host_key_verified,
            **{field: False for field in _FALSE_SAFETY_FIELDS},
        }
    )


def _get_verification(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    verification_id: UUID,
) -> ExternalDocumentSourceSftpTransportVerification:
    row = db.scalar(
        select(ExternalDocumentSourceSftpTransportVerification).where(
            ExternalDocumentSourceSftpTransportVerification.id == verification_id,
            ExternalDocumentSourceSftpTransportVerification.organization_id
            == organization_id,
            ExternalDocumentSourceSftpTransportVerification.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP transport verification not found"
        )
    return row


def _receipts(
    db: Session,
    row: ExternalDocumentSourceSftpTransportVerification,
) -> list[ExternalDocumentSourceSftpTransportVerificationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpTransportVerificationReceipt)
            .where(
                ExternalDocumentSourceSftpTransportVerificationReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpTransportVerificationReceipt.verification_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpTransportVerificationReceipt.sequence_number.asc()
            )
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceSftpTransportVerification,
    event_type: str,
    occurred_at: datetime,
    status_after: str,
    decision_hash: str,
    provider_network_performed: bool,
    ssh_transport_performed: bool,
    host_key_verification_performed: bool,
    host_key_verified: bool,
) -> None:
    receipts = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpTransportVerificationReceipt(
        organization_id=row.organization_id,
        verification_id=row.id,
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
        provider_network_performed=provider_network_performed,
        ssh_transport_performed=ssh_transport_performed,
        host_key_verification_performed=host_key_verification_performed,
        host_key_verified=host_key_verified,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _profile_destination(
    db: Session,
    execution: ExternalDocumentSourceSftpHandshakeExecution,
) -> tuple[str, int, str]:
    profile = get_external_document_source_profile(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
    )
    if (
        profile.status != "active"
        or profile.provider_kind != "sftp"
        or profile.profile_hash != execution.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification profile lineage drifted"
        )
    normalized = normalize_provider_config("sftp", profile.normalized_config)
    if normalized != profile.normalized_config or normalized["access_mode"] != "read_only":
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification destination configuration drifted"
        )
    return (
        normalized["hostname"],
        normalized["port"],
        normalized["host_key_fingerprint"],
    )


def _execution_for_verification(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceSftpHandshakeExecution:
    stmt = select(ExternalDocumentSourceSftpHandshakeExecution).where(
        ExternalDocumentSourceSftpHandshakeExecution.id == execution_id,
        ExternalDocumentSourceSftpHandshakeExecution.organization_id
        == organization_id,
        ExternalDocumentSourceSftpHandshakeExecution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    execution = db.scalar(stmt)
    if execution is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP handshake execution not found"
        )
    _ensure_handshake_execution_integrity(db, execution)
    if (
        execution.status != "completed"
        or not execution.handshake_authorization_consumed
        or execution.completion_hash is None
        or execution.authorization_terminal_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification requires an exact completed Phase 17.6-E execution"
        )
    return execution


def _validated_probe_outcome(
    probe: SftpTransportHostKeyProbeResult,
    *,
    pinned_host_key_fingerprint: str,
    destination_is_literal_ip: bool,
) -> dict:
    if not isinstance(probe, SftpTransportHostKeyProbeResult):
        return {
            "result_status": "failed",
            "failure_code": "invalid_adapter_result",
            "host_key_algorithm": None,
            "latency_class": None,
            "provider_network_performed": False,
            "ssh_transport_performed": False,
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    if (
        probe.authentication_performed
        or probe.sftp_session_opened
        or probe.remote_operation_performed
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport adapter violated the no-authentication/no-SFTP boundary"
        )

    if not probe.destination_policy_enforced:
        return {
            "result_status": "failed",
            "failure_code": "invalid_adapter_result",
            "host_key_algorithm": None,
            "latency_class": None,
            "provider_network_performed": bool(probe.provider_network_performed),
            "ssh_transport_performed": bool(probe.ssh_transport_performed),
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    if not destination_is_literal_ip and not probe.dns_resolution_performed:
        return {
            "result_status": "failed",
            "failure_code": "invalid_adapter_result",
            "host_key_algorithm": None,
            "latency_class": None,
            "provider_network_performed": bool(probe.provider_network_performed),
            "ssh_transport_performed": bool(probe.ssh_transport_performed),
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    if probe.failure_code is not None:
        if probe.failure_code not in _ADAPTER_FAILURE_CODES:
            failure_code = "invalid_adapter_result"
        else:
            failure_code = probe.failure_code
        return {
            "result_status": "failed",
            "failure_code": failure_code,
            "host_key_algorithm": None,
            "latency_class": (
                probe.latency_class
                if probe.latency_class in _ALLOWED_LATENCY_CLASSES
                else None
            ),
            "provider_network_performed": bool(probe.provider_network_performed),
            "ssh_transport_performed": bool(probe.ssh_transport_performed),
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    if (
        not probe.provider_network_performed
        or not probe.ssh_transport_performed
        or probe.latency_class not in _ALLOWED_LATENCY_CLASSES
        or not isinstance(probe.host_key_algorithm, str)
    ):
        return {
            "result_status": "failed",
            "failure_code": "invalid_adapter_result",
            "host_key_algorithm": None,
            "latency_class": None,
            "provider_network_performed": bool(probe.provider_network_performed),
            "ssh_transport_performed": bool(probe.ssh_transport_performed),
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    algorithm = probe.host_key_algorithm.strip()
    if algorithm not in _ALLOWED_HOST_KEY_ALGORITHMS:
        return {
            "result_status": "failed",
            "failure_code": "unsupported_host_key_algorithm",
            "host_key_algorithm": algorithm[:64] or None,
            "latency_class": probe.latency_class,
            "provider_network_performed": True,
            "ssh_transport_performed": True,
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    observed = probe.observed_host_key_fingerprint
    if not isinstance(observed, str) or not _OPENSSH_SHA256.fullmatch(
        observed.strip()
    ):
        return {
            "result_status": "failed",
            "failure_code": "invalid_adapter_result",
            "host_key_algorithm": algorithm,
            "latency_class": probe.latency_class,
            "provider_network_performed": True,
            "ssh_transport_performed": True,
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }

    observed = observed.strip()
    verified = hmac.compare_digest(observed, pinned_host_key_fingerprint)
    return {
        "result_status": "verified" if verified else "failed",
        "failure_code": None if verified else "host_key_mismatch",
        "host_key_algorithm": algorithm,
        "latency_class": probe.latency_class,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": verified,
    }


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpTransportVerification,
) -> None:
    if not row.credential_reference_stored or any(
        bool(getattr(row, field)) for field in _FALSE_SAFETY_FIELDS
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification safety boundary drifted"
        )

    execution = _execution_for_verification(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        execution_id=row.handshake_execution_id,
    )
    hostname, port, fingerprint = _profile_destination(db, execution)
    if (
        row.provider_kind != "sftp"
        or row.profile_hash != execution.profile_hash
        or row.handshake_execution_scope_hash != execution.scope_hash
        or row.handshake_execution_request_hash != execution.request_hash
        or row.handshake_execution_completion_hash != execution.completion_hash
        or row.authorization_terminal_hash != execution.authorization_terminal_hash
        or row.destination_hostname != hostname
        or row.destination_port != port
        or row.pinned_host_key_fingerprint != fingerprint
        or row.verification_limit != 1
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification upstream lineage drifted"
        )

    expected_scope = _scope_hash(
        execution=execution,
        destination_hostname=hostname,
        destination_port=port,
        pinned_host_key_fingerprint=fingerprint,
        adapter_kind=row.adapter_kind,
        request_key=row.request_key,
    )
    if (
        row.scope_hash != expected_scope
        or row.request_hash != _request_hash(row)
        or row.result_hash != _result_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification integrity failed"
        )

    if row.result_status == "verified":
        if (
            row.failure_code is not None
            or not row.provider_network_performed
            or not row.ssh_transport_performed
            or not row.host_key_verification_performed
            or not row.host_key_verified
            or row.host_key_algorithm not in _ALLOWED_HOST_KEY_ALGORITHMS
            or row.latency_class not in _ALLOWED_LATENCY_CLASSES
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP transport verification success facts drifted"
            )
    elif row.result_status == "failed":
        if row.failure_code is None or row.host_key_verified:
            raise ExternalDocumentSourceConflictError(
                "SFTP transport verification failure facts drifted"
            )
    else:
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification result status is invalid"
        )

    receipts = _receipts(db, row)
    if len(receipts) != 2 or [receipt.event_type for receipt in receipts] != [
        "requested",
        "completed",
    ]:
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification receipt lifecycle is incomplete"
        )

    prior: str | None = None
    for sequence, receipt in enumerate(receipts, start=1):
        if (
            receipt.sequence_number != sequence
            or receipt.prior_receipt_hash != prior
            or receipt.scope_hash != row.scope_hash
            or receipt.actor_id != row.requested_by_id
            or receipt.reason != row.request_reason
            or not receipt.credential_reference_stored
            or any(bool(getattr(receipt, field)) for field in _FALSE_SAFETY_FIELDS)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP transport verification receipt lineage drifted"
            )
        if receipt.event_type == "requested":
            expected_status = "requested"
            expected_time = row.requested_at
            expected_decision = row.request_hash
            expected_network = False
            expected_transport = False
            expected_verification = False
            expected_verified = False
        else:
            expected_status = row.result_status
            expected_time = row.checked_at
            expected_decision = row.result_hash
            expected_network = row.provider_network_performed
            expected_transport = row.ssh_transport_performed
            expected_verification = row.host_key_verification_performed
            expected_verified = row.host_key_verified
        if (
            receipt.status_after != expected_status
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.decision_hash != expected_decision
            or receipt.provider_network_performed != expected_network
            or receipt.ssh_transport_performed != expected_transport
            or receipt.host_key_verification_performed != expected_verification
            or receipt.host_key_verified != expected_verified
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP transport verification receipt integrity failed"
            )
        prior = receipt.receipt_hash


def verify_external_document_source_sftp_transport(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    handshake_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        request_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpTransportVerification).where(
            ExternalDocumentSourceSftpTransportVerification.organization_id
            == organization_id,
            ExternalDocumentSourceSftpTransportVerification.profile_id == profile_id,
            ExternalDocumentSourceSftpTransportVerification.handshake_execution_id
            == handshake_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP transport verification"
            )
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceSftpTransportVerification).where(
            ExternalDocumentSourceSftpTransportVerification.organization_id
            == organization_id,
            ExternalDocumentSourceSftpTransportVerification.profile_id == profile_id,
            ExternalDocumentSourceSftpTransportVerification.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "Conflicting replay for SFTP transport verification request_key"
        )

    adapter = _TRANSPORT_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP transport verification adapter is unavailable"
        )
    adapter_kind = _normalize_adapter_kind(adapter.adapter_kind)

    execution = _execution_for_verification(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=handshake_execution_id,
        for_update=True,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpTransportVerification).where(
            ExternalDocumentSourceSftpTransportVerification.handshake_execution_id
            == handshake_execution_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP transport verification"
            )
        return existing, "unchanged"

    hostname, port, fingerprint = _profile_destination(db, execution)
    current = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        execution=execution,
        destination_hostname=hostname,
        destination_port=port,
        pinned_host_key_fingerprint=fingerprint,
        adapter_kind=adapter_kind,
        request_key=normalized_key,
    )

    if _literal_destination_denied(hostname):
        outcome = {
            "result_status": "failed",
            "failure_code": "destination_policy_violation",
            "host_key_algorithm": None,
            "latency_class": None,
            "provider_network_performed": False,
            "ssh_transport_performed": False,
            "host_key_verification_performed": False,
            "host_key_verified": False,
        }
    else:
        probe_request = SftpTransportHostKeyProbeRequest(
            hostname=hostname,
            port=port,
            connect_timeout_seconds=5,
            handshake_timeout_seconds=5,
            max_connection_attempts=1,
            allow_private_destinations=False,
            allow_redirects=False,
            allow_proxy_retargeting=False,
            pin_policy_checked_address=True,
        )
        try:
            probe = adapter.probe(probe_request)
        except Exception:
            outcome = {
                "result_status": "failed",
                "failure_code": "adapter_error",
                "host_key_algorithm": None,
                "latency_class": None,
                "provider_network_performed": True,
                "ssh_transport_performed": False,
                "host_key_verification_performed": False,
                "host_key_verified": False,
            }
        else:
            outcome = _validated_probe_outcome(
                probe,
                pinned_host_key_fingerprint=fingerprint,
                destination_is_literal_ip=_is_literal_ip(hostname),
            )

    checked_at = max(current, _utc_now())
    row = ExternalDocumentSourceSftpTransportVerification(
        organization_id=organization_id,
        profile_id=profile_id,
        handshake_execution_id=execution.id,
        provider_kind="sftp",
        profile_hash=execution.profile_hash,
        handshake_execution_scope_hash=execution.scope_hash,
        handshake_execution_request_hash=execution.request_hash,
        handshake_execution_completion_hash=execution.completion_hash,
        authorization_terminal_hash=execution.authorization_terminal_hash,
        destination_hostname=hostname,
        destination_port=port,
        pinned_host_key_fingerprint=fingerprint,
        adapter_kind=adapter_kind,
        verification_limit=1,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        checked_at=checked_at,
        result_status=outcome["result_status"],
        failure_code=outcome["failure_code"],
        host_key_algorithm=outcome["host_key_algorithm"],
        latency_class=outcome["latency_class"],
        result_hash="0" * 64,
        credential_reference_stored=True,
        provider_network_performed=outcome["provider_network_performed"],
        ssh_transport_performed=outcome["ssh_transport_performed"],
        host_key_verification_performed=outcome[
            "host_key_verification_performed"
        ],
        host_key_verified=outcome["host_key_verified"],
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    db.add(row)
    db.flush()

    row.request_hash = _request_hash(row)
    row.result_hash = _result_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="requested",
        occurred_at=current,
        status_after="requested",
        decision_hash=row.request_hash,
        provider_network_performed=False,
        ssh_transport_performed=False,
        host_key_verification_performed=False,
        host_key_verified=False,
    )
    _append_receipt(
        db,
        row=row,
        event_type="completed",
        occurred_at=checked_at,
        status_after=row.result_status,
        decision_hash=row.result_hash,
        provider_network_performed=row.provider_network_performed,
        ssh_transport_performed=row.ssh_transport_performed,
        host_key_verification_performed=row.host_key_verification_performed,
        host_key_verified=row.host_key_verified,
    )
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_transport_verification(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    verification_id: UUID,
):
    row = _get_verification(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        verification_id=verification_id,
    )
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_transport_verification_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    verification_id: UUID,
):
    row = get_external_document_source_sftp_transport_verification(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        verification_id=verification_id,
    )
    return _receipts(db, row)
