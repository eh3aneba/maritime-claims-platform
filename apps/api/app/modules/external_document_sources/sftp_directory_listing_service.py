from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
    normalize_provider_config,
)
from app.modules.external_document_sources.sftp_credential_reference_service import (
    get_external_document_source_sftp_credential_reference,
)
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
    ExternalDocumentSourceSftpDirectoryListingEntry,
    ExternalDocumentSourceSftpDirectoryListingReceipt,
)
from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    _ensure_integrity as _ensure_activation_integrity,
)


_SAFE_ADAPTER_KIND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ENTRY_KINDS = frozenset({"file", "directory", "symlink", "other"})
_ALLOWED_AUTH_METHODS = frozenset({"password", "public_key"})
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_ALLOWED_FAILURE_CODES = frozenset({
    "credential_resolution_failed",
    "credential_unavailable",
    "connection_failed",
    "connection_timeout",
    "host_key_revalidation_failed",
    "authentication_failed",
    "authentication_timeout",
    "sftp_subsystem_activation_failed",
    "listing_failed",
    "listing_timeout",
    "path_policy_violation",
    "symlink_escape_detected",
    "too_many_entries",
    "oversized_metadata",
    "unsupported_entry_metadata",
})
_MAX_ENTRIES = 100
_MAX_METADATA_BYTES = 131072
_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "remote_stat_performed",
    "remote_read_performed",
    "remote_write_performed",
    "remote_rename_performed",
    "remote_delete_performed",
    "command_executed",
    "checkpoint_created",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


@dataclass(frozen=True)
class SftpDirectoryMetadataEntry:
    relative_path: str
    entry_kind: str
    byte_size: int | None = None
    modified_at: datetime | None = None
    metadata_id_hash: str | None = None


@dataclass(frozen=True)
class SftpDirectoryListingRequest:
    hostname: str
    port: int
    username: str
    pinned_host_key_fingerprint: str
    authentication_kind: str
    reference_backend: str
    reference_namespace: str
    reference_name: str
    reference_version: str | None
    remote_root_path: str
    relative_path: str
    effective_remote_path: str
    max_entries: int = _MAX_ENTRIES
    max_pages: int = 1
    connect_timeout_seconds: int = 5
    authentication_timeout_seconds: int = 5
    listing_timeout_seconds: int = 7
    total_timeout_seconds: int = 17
    max_connection_attempts: int = 1
    max_authentication_attempts: int = 1
    max_listing_attempts: int = 1
    allow_private_destinations: bool = False
    allow_redirects: bool = False
    allow_proxy_retargeting: bool = False
    read_only_intent: bool = True
    recursive: bool = False
    follow_symlinks: bool = False


@dataclass(frozen=True)
class SftpDirectoryListingResult:
    failure_code: str | None = None
    authentication_method: str | None = None
    latency_class: str | None = None
    entries: tuple[SftpDirectoryMetadataEntry, ...] = ()
    truncated: bool = False
    page_count: int = 0
    secret_resolution_performed: bool = False
    provider_network_performed: bool = False
    ssh_transport_performed: bool = False
    host_key_verification_performed: bool = False
    host_key_verified: bool = False
    authentication_performed: bool = False
    authentication_succeeded: bool = False
    sftp_session_opened: bool = False
    remote_list_performed: bool = False
    sftp_session_closed: bool = False
    credential_persisted: bool = False
    session_persisted: bool = False
    raw_response_persisted: bool = False
    remote_stat_performed: bool = False
    remote_read_performed: bool = False
    remote_write_performed: bool = False
    remote_rename_performed: bool = False
    remote_delete_performed: bool = False
    command_executed: bool = False
    symlink_escape_detected: bool = False


class SftpDirectoryListingAdapter(Protocol):
    adapter_kind: str

    def list_metadata(self, request: SftpDirectoryListingRequest) -> SftpDirectoryListingResult: ...


_LISTING_ADAPTER: SftpDirectoryListingAdapter | None = None


def register_external_document_source_sftp_directory_listing_adapter(adapter: SftpDirectoryListingAdapter) -> None:
    global _LISTING_ADAPTER
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_ADAPTER_KIND.fullmatch(adapter_kind):
        raise ValueError("SFTP directory listing adapter kind is invalid")
    _LISTING_ADAPTER = adapter


def clear_external_document_source_sftp_directory_listing_adapter() -> None:
    global _LISTING_ADAPTER
    _LISTING_ADAPTER = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _normalize_relative_path(value: str, *, maximum: int = 512, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError("relative_path must be a string")
    raw = value.strip()
    if not raw:
        if allow_empty:
            return ""
        raise ExternalDocumentSourceValidationError("relative_path must not be empty")
    if len(raw) > maximum or raw.startswith("/") or "\\" in raw or any(ord(char) < 32 for char in raw):
        raise ExternalDocumentSourceValidationError("relative_path is outside the bounded POSIX path policy")
    segments = raw.split("/")
    if any(segment == ".." for segment in segments):
        raise ExternalDocumentSourceValidationError("relative_path must not contain parent traversal")
    normalized = "/".join(segment for segment in segments if segment not in {"", "."})
    if not normalized and not allow_empty:
        raise ExternalDocumentSourceValidationError("relative_path must not normalize to empty")
    if len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError("relative_path exceeds the bounded path length")
    return normalized


def _effective_remote_path(root: str, relative_path: str) -> str:
    if not relative_path:
        return root
    if root == "/":
        return "/" + relative_path
    return root.rstrip("/") + "/" + relative_path


def _normalize_adapter_kind(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_ADAPTER_KIND.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter kind is invalid")
    return normalized


def _root_hash(root: str) -> str:
    return _canonical_hash({"remote_root_path": root})


def _scope_hash(*, activation, binding, normalized_config: dict, adapter_kind: str, relative_path: str, request_key: str) -> str:
    root = normalized_config["remote_root_path"]
    return _canonical_hash({
        "organization_id": str(activation.organization_id),
        "profile_id": str(activation.profile_id),
        "session_activation_id": str(activation.id),
        "session_activation_scope_hash": activation.scope_hash,
        "session_activation_request_hash": activation.request_hash,
        "session_activation_result_hash": activation.result_hash,
        "credential_reference_binding_id": str(binding.id),
        "locator_hash": binding.locator_hash,
        "authentication_kind": binding.authentication_kind,
        "reference_backend": binding.reference_backend,
        "destination_hostname": activation.destination_hostname,
        "destination_port": activation.destination_port,
        "pinned_host_key_fingerprint": activation.pinned_host_key_fingerprint,
        "username": normalized_config["username"],
        "remote_root_path_hash": _root_hash(root),
        "relative_path": relative_path,
        "listing_adapter_kind": adapter_kind,
        "request_key": request_key,
        "listing_limit": 1,
        "max_entries": _MAX_ENTRIES,
        "recursive": False,
        "follow_symlinks": False,
    })


def _request_hash(row: ExternalDocumentSourceSftpDirectoryListing) -> str:
    return _canonical_hash({
        "listing_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_relative_path": row.request_relative_path,
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
        "remote_list_performed": False,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    })


def _entry_hash(listing_id: UUID, item: dict, index: int) -> str:
    return _canonical_hash({
        "listing_id": str(listing_id),
        "entry_index": index,
        "relative_path": item["relative_path"],
        "entry_name": item["entry_name"],
        "entry_kind": item["entry_kind"],
        "byte_size": item["byte_size"],
        "modified_at": _iso(item["modified_at"]),
        "metadata_id_hash": item["metadata_id_hash"],
    })


def _items_hash(entry_hashes: list[str]) -> str:
    return _canonical_hash({"entry_hashes": entry_hashes})


def _result_hash(row: ExternalDocumentSourceSftpDirectoryListing) -> str:
    return _canonical_hash({
        "listing_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completed_at": _iso(row.completed_at),
        "result_status": row.result_status,
        "failure_code": row.failure_code,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "entry_count": row.entry_count,
        "page_count": row.page_count,
        "truncated": row.truncated,
        "items_hash": row.items_hash,
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
        "remote_list_performed": row.remote_list_performed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    })


def _receipt_hash(receipt: ExternalDocumentSourceSftpDirectoryListingReceipt) -> str:
    return _canonical_hash({
        "organization_id": str(receipt.organization_id),
        "listing_id": str(receipt.listing_id),
        "sequence_number": receipt.sequence_number,
        "event_type": receipt.event_type,
        "status_after": receipt.status_after,
        "actor_id": str(receipt.actor_id),
        "occurred_at": _iso(receipt.occurred_at),
        "reason": receipt.reason,
        "scope_hash": receipt.scope_hash,
        "decision_hash": receipt.decision_hash,
        "prior_receipt_hash": receipt.prior_receipt_hash,
        "credential_reference_stored": receipt.credential_reference_stored,
        "secret_resolution_performed": receipt.secret_resolution_performed,
        "provider_network_performed": receipt.provider_network_performed,
        "ssh_transport_performed": receipt.ssh_transport_performed,
        "host_key_verification_performed": receipt.host_key_verification_performed,
        "host_key_verified": receipt.host_key_verified,
        "authentication_performed": receipt.authentication_performed,
        "authentication_succeeded": receipt.authentication_succeeded,
        "sftp_session_opened": receipt.sftp_session_opened,
        "sftp_session_closed": receipt.sftp_session_closed,
        "remote_list_performed": receipt.remote_list_performed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    })


def _entries(db: Session, row: ExternalDocumentSourceSftpDirectoryListing):
    return db.scalars(
        select(ExternalDocumentSourceSftpDirectoryListingEntry)
        .where(ExternalDocumentSourceSftpDirectoryListingEntry.listing_id == row.id)
        .order_by(ExternalDocumentSourceSftpDirectoryListingEntry.entry_index.asc())
    ).all()


def _receipts(db: Session, row: ExternalDocumentSourceSftpDirectoryListing):
    return db.scalars(
        select(ExternalDocumentSourceSftpDirectoryListingReceipt)
        .where(ExternalDocumentSourceSftpDirectoryListingReceipt.listing_id == row.id)
        .order_by(ExternalDocumentSourceSftpDirectoryListingReceipt.sequence_number.asc())
    ).all()


def _load_verified_lineage(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    activation_id: UUID,
    for_update: bool,
):
    stmt = select(ExternalDocumentSourceSftpSessionActivation).where(
        ExternalDocumentSourceSftpSessionActivation.id == activation_id,
        ExternalDocumentSourceSftpSessionActivation.organization_id == organization_id,
        ExternalDocumentSourceSftpSessionActivation.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    activation = db.scalar(stmt)
    if activation is None:
        raise ExternalDocumentSourceNotFoundError("SFTP session activation not found")
    _ensure_activation_integrity(db, activation)
    if (
        activation.result_status != "activated"
        or not activation.secret_resolution_performed
        or not activation.provider_network_performed
        or not activation.ssh_transport_performed
        or not activation.host_key_verified
        or not activation.authentication_succeeded
        or not activation.sftp_session_opened
        or not activation.sftp_session_closed
    ):
        raise ExternalDocumentSourceConflictError("SFTP directory listing requires an exact activated Phase 17.6-G result")

    binding = get_external_document_source_sftp_credential_reference(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=activation.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("SFTP credential reference is not active")
    if (
        activation.credential_reference_binding_id != binding.id
        or activation.locator_hash != binding.locator_hash
        or activation.authentication_kind != binding.authentication_kind
        or activation.reference_backend != binding.reference_backend
    ):
        raise ExternalDocumentSourceConflictError("SFTP directory listing credential lineage drifted")

    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    normalized = normalize_provider_config("sftp", profile.normalized_config)
    if (
        profile.status != "active"
        or profile.provider_kind != "sftp"
        or normalized != profile.normalized_config
        or normalized["access_mode"] != "read_only"
        or profile.profile_hash != activation.profile_hash
        or activation.destination_hostname != normalized["hostname"]
        or activation.destination_port != normalized["port"]
        or activation.pinned_host_key_fingerprint != normalized["host_key_fingerprint"]
    ):
        raise ExternalDocumentSourceConflictError("SFTP directory listing profile/destination lineage drifted")
    return activation, binding, normalized


def _normalized_entry(entry: SftpDirectoryMetadataEntry, *, request_relative_path: str) -> dict:
    if not isinstance(entry, SftpDirectoryMetadataEntry):
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter returned unsupported entry metadata")
    relative_path = _normalize_relative_path(entry.relative_path, maximum=768, allow_empty=False)
    parent, _, name = relative_path.rpartition("/")
    if parent != request_relative_path:
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter exceeded the non-recursive path boundary")
    if not name or len(name) > 255:
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter returned an invalid entry name")
    if entry.entry_kind not in _ALLOWED_ENTRY_KINDS:
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter returned an unsupported entry kind")
    if entry.byte_size is not None:
        if entry.entry_kind != "file" or not isinstance(entry.byte_size, int) or entry.byte_size < 0 or entry.byte_size > 9223372036854775807:
            raise ExternalDocumentSourceConflictError("SFTP directory listing adapter returned an invalid byte size")
    metadata_id_hash = entry.metadata_id_hash
    if metadata_id_hash is not None and (not isinstance(metadata_id_hash, str) or not _HEX_64.fullmatch(metadata_id_hash)):
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter returned an invalid metadata identifier hash")
    modified_at = _aware(entry.modified_at) if entry.modified_at is not None else None
    return {
        "relative_path": relative_path,
        "entry_name": name,
        "entry_kind": entry.entry_kind,
        "byte_size": entry.byte_size,
        "modified_at": modified_at,
        "metadata_id_hash": metadata_id_hash,
    }


def _failure_outcome(result: SftpDirectoryListingResult, failure_code: str) -> dict:
    method = result.authentication_method if result.authentication_method in _ALLOWED_AUTH_METHODS else None
    latency = result.latency_class if result.latency_class in _ALLOWED_LATENCY_CLASSES else None
    return {
        "result_status": "failed",
        "failure_code": failure_code,
        "authentication_method": method,
        "latency_class": latency,
        "entries": [],
        "entry_count": 0,
        "page_count": result.page_count if result.page_count in {0, 1} else 0,
        "truncated": False,
        "secret_resolution_performed": bool(result.secret_resolution_performed),
        "provider_network_performed": bool(result.provider_network_performed),
        "ssh_transport_performed": bool(result.ssh_transport_performed),
        "host_key_verification_performed": bool(result.host_key_verification_performed),
        "host_key_verified": bool(result.host_key_verified),
        "authentication_performed": bool(result.authentication_performed),
        "authentication_succeeded": bool(result.authentication_succeeded),
        "sftp_session_opened": bool(result.sftp_session_opened),
        "sftp_session_closed": bool(result.sftp_session_closed),
        "remote_list_performed": bool(result.remote_list_performed),
    }


def _validated_result(result: SftpDirectoryListingResult, *, expected_auth_kind: str, request_relative_path: str) -> dict:
    if not isinstance(result, SftpDirectoryListingResult):
        return _failure_outcome(SftpDirectoryListingResult(), "invalid_adapter_result")

    if (
        result.credential_persisted
        or result.session_persisted
        or result.raw_response_persisted
        or result.remote_stat_performed
        or result.remote_read_performed
        or result.remote_write_performed
        or result.remote_rename_performed
        or result.remote_delete_performed
        or result.command_executed
    ):
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter violated the read-only metadata boundary")
    if result.sftp_session_opened and not result.sftp_session_closed:
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter did not prove immediate session closure")
    if result.host_key_verified and not result.host_key_verification_performed:
        return _failure_outcome(result, "invalid_adapter_result")
    if result.authentication_succeeded and not result.authentication_performed:
        return _failure_outcome(result, "invalid_adapter_result")
    if result.sftp_session_opened and not result.authentication_succeeded:
        return _failure_outcome(result, "invalid_adapter_result")
    if result.remote_list_performed and not result.sftp_session_opened:
        return _failure_outcome(result, "invalid_adapter_result")

    if result.symlink_escape_detected:
        return _failure_outcome(result, "symlink_escape_detected")
    if result.failure_code is not None:
        failure = result.failure_code if result.failure_code in _ALLOWED_FAILURE_CODES else "invalid_adapter_result"
        if result.entries:
            failure = "invalid_adapter_result"
        return _failure_outcome(result, failure)

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
        or not result.remote_list_performed
        or not result.sftp_session_closed
        or result.page_count != 1
    ):
        return _failure_outcome(result, "invalid_adapter_result")

    if len(result.entries) > _MAX_ENTRIES:
        return _failure_outcome(result, "too_many_entries")

    normalized_entries = [_normalized_entry(entry, request_relative_path=request_relative_path) for entry in result.entries]
    paths = [entry["relative_path"] for entry in normalized_entries]
    if len(paths) != len(set(paths)):
        return _failure_outcome(result, "unsupported_entry_metadata")

    projection = [
        {
            "relative_path": entry["relative_path"],
            "entry_name": entry["entry_name"],
            "entry_kind": entry["entry_kind"],
            "byte_size": entry["byte_size"],
            "modified_at": _iso(entry["modified_at"]),
            "metadata_id_hash": entry["metadata_id_hash"],
        }
        for entry in normalized_entries
    ]
    if len(json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > _MAX_METADATA_BYTES:
        return _failure_outcome(result, "oversized_metadata")

    return {
        "result_status": "listed",
        "failure_code": None,
        "authentication_method": result.authentication_method,
        "latency_class": result.latency_class,
        "entries": normalized_entries,
        "entry_count": len(normalized_entries),
        "page_count": 1,
        "truncated": bool(result.truncated),
        "secret_resolution_performed": True,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": True,
        "authentication_performed": True,
        "authentication_succeeded": True,
        "sftp_session_opened": True,
        "sftp_session_closed": True,
        "remote_list_performed": True,
    }


def _append_receipts(db: Session, row: ExternalDocumentSourceSftpDirectoryListing) -> None:
    requested = ExternalDocumentSourceSftpDirectoryListingReceipt(
        organization_id=row.organization_id,
        listing_id=row.id,
        sequence_number=1,
        event_type="requested",
        status_after="requested",
        actor_id=row.requested_by_id,
        occurred_at=row.requested_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=row.request_hash,
        prior_receipt_hash=None,
        receipt_hash="0" * 64,
        credential_reference_stored=True,
        secret_resolution_performed=False,
        provider_network_performed=False,
        ssh_transport_performed=False,
        host_key_verification_performed=False,
        host_key_verified=False,
        authentication_performed=False,
        authentication_succeeded=False,
        sftp_session_opened=False,
        sftp_session_closed=False,
        remote_list_performed=False,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    requested.receipt_hash = _receipt_hash(requested)
    completed = ExternalDocumentSourceSftpDirectoryListingReceipt(
        organization_id=row.organization_id,
        listing_id=row.id,
        sequence_number=2,
        event_type="completed",
        status_after=row.result_status,
        actor_id=row.requested_by_id,
        occurred_at=row.completed_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=row.result_hash,
        prior_receipt_hash=requested.receipt_hash,
        receipt_hash="0" * 64,
        credential_reference_stored=True,
        secret_resolution_performed=row.secret_resolution_performed,
        provider_network_performed=row.provider_network_performed,
        ssh_transport_performed=row.ssh_transport_performed,
        host_key_verification_performed=row.host_key_verification_performed,
        host_key_verified=row.host_key_verified,
        authentication_performed=row.authentication_performed,
        authentication_succeeded=row.authentication_succeeded,
        sftp_session_opened=row.sftp_session_opened,
        sftp_session_closed=row.sftp_session_closed,
        remote_list_performed=row.remote_list_performed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    completed.receipt_hash = _receipt_hash(completed)
    db.add_all([requested, completed])


def _ensure_integrity(db: Session, row: ExternalDocumentSourceSftpDirectoryListing) -> None:
    activation, binding, normalized = _load_verified_lineage(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        activation_id=row.session_activation_id,
        for_update=False,
    )
    expected_root = normalized["remote_root_path"]
    if (
        row.provider_kind != "sftp"
        or row.profile_hash != activation.profile_hash
        or row.session_activation_scope_hash != activation.scope_hash
        or row.session_activation_request_hash != activation.request_hash
        or row.session_activation_result_hash != activation.result_hash
        or row.credential_reference_binding_id != binding.id
        or row.locator_hash != binding.locator_hash
        or row.authentication_kind != binding.authentication_kind
        or row.reference_backend != binding.reference_backend
        or row.destination_hostname != activation.destination_hostname
        or row.destination_port != activation.destination_port
        or row.pinned_host_key_fingerprint != activation.pinned_host_key_fingerprint
        or row.remote_root_path != expected_root
        or row.remote_root_path_hash != _root_hash(expected_root)
        or row.listing_limit != 1
        or row.max_entries != _MAX_ENTRIES
        or row.scope_hash != _scope_hash(
            activation=activation,
            binding=binding,
            normalized_config=normalized,
            adapter_kind=row.listing_adapter_kind,
            relative_path=row.request_relative_path,
            request_key=row.request_key,
        )
        or row.request_hash != _request_hash(row)
    ):
        raise ExternalDocumentSourceConflictError("SFTP directory listing integrity failed")

    for field in _FALSE_SAFETY_FIELDS:
        if getattr(row, field):
            raise ExternalDocumentSourceConflictError("SFTP directory listing safety boundary integrity failed")

    entries = _entries(db, row)
    if len(entries) != row.entry_count:
        raise ExternalDocumentSourceConflictError("SFTP directory listing entry count integrity failed")
    entry_hashes: list[str] = []
    for index, entry in enumerate(entries):
        item = {
            "relative_path": entry.relative_path,
            "entry_name": entry.entry_name,
            "entry_kind": entry.entry_kind,
            "byte_size": entry.byte_size,
            "modified_at": entry.modified_at,
            "metadata_id_hash": entry.metadata_id_hash,
        }
        expected_hash = _entry_hash(row.id, item, index)
        if entry.entry_index != index or entry.entry_hash != expected_hash:
            raise ExternalDocumentSourceConflictError("SFTP directory listing entry integrity failed")
        entry_hashes.append(expected_hash)

    if row.result_status == "listed":
        if row.items_hash != _items_hash(entry_hashes) or row.page_count != 1 or not row.remote_list_performed:
            raise ExternalDocumentSourceConflictError("SFTP directory listing result integrity failed")
    else:
        if entries or row.items_hash is not None or row.entry_count != 0 or row.truncated:
            raise ExternalDocumentSourceConflictError("SFTP directory listing failed-result integrity failed")

    if row.result_hash != _result_hash(row):
        raise ExternalDocumentSourceConflictError("SFTP directory listing result hash integrity failed")

    receipts = _receipts(db, row)
    if len(receipts) != 2:
        raise ExternalDocumentSourceConflictError("SFTP directory listing receipt chain is incomplete")
    expected = (
        (1, "requested", row.requested_at, "requested", row.request_hash, None),
        (2, "completed", row.completed_at, row.result_status, row.result_hash, receipts[0].receipt_hash),
    )
    for receipt, facts in zip(receipts, expected, strict=True):
        seq, event, at, status_after, decision_hash, prior = facts
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
            raise ExternalDocumentSourceConflictError("SFTP directory listing receipt integrity failed")


def create_external_document_source_sftp_directory_listing(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    session_activation_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    relative_path: str = "",
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    normalized_relative_path = _normalize_relative_path(relative_path)

    activation, binding, normalized_config = _load_verified_lineage(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        activation_id=session_activation_id,
        for_update=True,
    )

    existing = db.scalar(select(ExternalDocumentSourceSftpDirectoryListing).where(
        ExternalDocumentSourceSftpDirectoryListing.session_activation_id == session_activation_id
    ))
    if existing is not None:
        if existing.organization_id != organization_id or existing.profile_id != profile_id:
            raise ExternalDocumentSourceNotFoundError("SFTP session activation not found")
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
            or existing.request_relative_path != normalized_relative_path
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP directory listing")
        return existing, _entries(db, existing), "unchanged"

    collision = db.scalar(select(ExternalDocumentSourceSftpDirectoryListing).where(
        ExternalDocumentSourceSftpDirectoryListing.organization_id == organization_id,
        ExternalDocumentSourceSftpDirectoryListing.profile_id == profile_id,
        ExternalDocumentSourceSftpDirectoryListing.request_key == normalized_key,
    ))
    if collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP directory listing request_key")

    adapter = _LISTING_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError("SFTP directory listing adapter is unavailable")
    adapter_kind = _normalize_adapter_kind(adapter.adapter_kind)

    root = normalized_config["remote_root_path"]
    requested_at = _aware(now or _utc_now())
    request = SftpDirectoryListingRequest(
        hostname=activation.destination_hostname,
        port=activation.destination_port,
        username=normalized_config["username"],
        pinned_host_key_fingerprint=activation.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
        remote_root_path=root,
        relative_path=normalized_relative_path,
        effective_remote_path=_effective_remote_path(root, normalized_relative_path),
    )
    try:
        adapter_result = adapter.list_metadata(request)
    except Exception:
        adapter_result = SftpDirectoryListingResult(failure_code="adapter_error")

    if isinstance(adapter_result, SftpDirectoryListingResult) and adapter_result.failure_code == "adapter_error":
        outcome = _failure_outcome(adapter_result, "adapter_error")
    else:
        outcome = _validated_result(
            adapter_result,
            expected_auth_kind=binding.authentication_kind,
            request_relative_path=normalized_relative_path,
        )

    completed_at = max(requested_at, _utc_now())
    listing_id = uuid4()
    scope_hash = _scope_hash(
        activation=activation,
        binding=binding,
        normalized_config=normalized_config,
        adapter_kind=adapter_kind,
        relative_path=normalized_relative_path,
        request_key=normalized_key,
    )
    row = ExternalDocumentSourceSftpDirectoryListing(
        id=listing_id,
        organization_id=organization_id,
        profile_id=profile_id,
        session_activation_id=activation.id,
        credential_reference_binding_id=binding.id,
        provider_kind="sftp",
        profile_hash=activation.profile_hash,
        session_activation_scope_hash=activation.scope_hash,
        session_activation_request_hash=activation.request_hash,
        session_activation_result_hash=activation.result_hash,
        locator_hash=binding.locator_hash,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        destination_hostname=activation.destination_hostname,
        destination_port=activation.destination_port,
        pinned_host_key_fingerprint=activation.pinned_host_key_fingerprint,
        remote_root_path=root,
        remote_root_path_hash=_root_hash(root),
        request_relative_path=normalized_relative_path,
        listing_adapter_kind=adapter_kind,
        listing_limit=1,
        max_entries=_MAX_ENTRIES,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        completed_at=completed_at,
        result_status=outcome["result_status"],
        failure_code=outcome["failure_code"],
        authentication_method=outcome["authentication_method"],
        latency_class=outcome["latency_class"],
        entry_count=outcome["entry_count"],
        page_count=outcome["page_count"],
        truncated=outcome["truncated"],
        items_hash=None,
        result_hash="0" * 64,
        credential_reference_stored=True,
        secret_resolution_performed=outcome["secret_resolution_performed"],
        provider_network_performed=outcome["provider_network_performed"],
        ssh_transport_performed=outcome["ssh_transport_performed"],
        host_key_verification_performed=outcome["host_key_verification_performed"],
        host_key_verified=outcome["host_key_verified"],
        authentication_performed=outcome["authentication_performed"],
        authentication_succeeded=outcome["authentication_succeeded"],
        sftp_session_opened=outcome["sftp_session_opened"],
        sftp_session_closed=outcome["sftp_session_closed"],
        remote_list_performed=outcome["remote_list_performed"],
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    )
    row.request_hash = _request_hash(row)

    entry_rows: list[ExternalDocumentSourceSftpDirectoryListingEntry] = []
    entry_hashes: list[str] = []
    for index, item in enumerate(outcome["entries"]):
        entry_hash = _entry_hash(listing_id, item, index)
        entry_hashes.append(entry_hash)
        entry_rows.append(ExternalDocumentSourceSftpDirectoryListingEntry(
            organization_id=organization_id,
            listing_id=listing_id,
            entry_index=index,
            relative_path=item["relative_path"],
            entry_name=item["entry_name"],
            entry_kind=item["entry_kind"],
            byte_size=item["byte_size"],
            modified_at=item["modified_at"],
            metadata_id_hash=item["metadata_id_hash"],
            entry_hash=entry_hash,
        ))
    if row.result_status == "listed":
        row.items_hash = _items_hash(entry_hashes)
    row.result_hash = _result_hash(row)

    db.add(row)
    db.add_all(entry_rows)
    _append_receipts(db, row)
    db.flush()
    _ensure_integrity(db, row)
    return row, entry_rows, "completed"


def get_external_document_source_sftp_directory_listing(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    listing_id: UUID,
):
    row = db.scalar(select(ExternalDocumentSourceSftpDirectoryListing).where(
        ExternalDocumentSourceSftpDirectoryListing.id == listing_id,
        ExternalDocumentSourceSftpDirectoryListing.organization_id == organization_id,
        ExternalDocumentSourceSftpDirectoryListing.profile_id == profile_id,
    ))
    if row is None:
        raise ExternalDocumentSourceNotFoundError("SFTP directory listing not found")
    _ensure_integrity(db, row)
    return row, _entries(db, row)


def list_external_document_source_sftp_directory_listing_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    listing_id: UUID,
):
    row, _ = get_external_document_source_sftp_directory_listing(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        listing_id=listing_id,
    )
    return _receipts(db, row)
