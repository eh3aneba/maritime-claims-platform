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
from app.modules.external_document_sources.sftp_credential_reference_service import (
    get_external_document_source_sftp_credential_reference,
)
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
    ExternalDocumentSourceSftpDirectoryListingEntry,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    _ensure_integrity as _ensure_listing_integrity,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    MAX_SFTP_CONTENT_PROOF_BYTES,
    ExternalDocumentSourceSftpFileContentProof,
    ExternalDocumentSourceSftpFileContentProofReceipt,
)


_SAFE_ADAPTER_KIND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_AUTH_METHODS = frozenset({"password", "public_key"})
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "session_stored",
    "raw_response_stored",
    "remote_content_stored",
    "remote_content_returned",
    "remote_content_logged",
    "content_parsed",
    "content_extracted",
    "remote_list_performed",
    "remote_stat_performed",
    "remote_write_performed",
    "remote_rename_performed",
    "remote_delete_performed",
    "remote_mkdir_performed",
    "remote_chmod_performed",
    "remote_chown_performed",
    "remote_touch_performed",
    "command_executed",
    "checkpoint_created",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


@dataclass(frozen=True)
class SftpFileContentReadRequest:
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
    entry_relative_path: str
    effective_remote_path: str
    max_content_bytes: int = MAX_SFTP_CONTENT_PROOF_BYTES
    max_chunk_bytes: int = 65536
    connect_timeout_seconds: int = 5
    authentication_timeout_seconds: int = 5
    read_timeout_seconds: int = 12
    total_timeout_seconds: int = 22
    max_connection_attempts: int = 1
    max_authentication_attempts: int = 1
    max_read_attempts: int = 1
    allow_private_destinations: bool = False
    allow_redirects: bool = False
    allow_proxy_retargeting: bool = False
    read_only_intent: bool = True
    exact_file_only: bool = True
    follow_symlinks: bool = False


@dataclass(frozen=True)
class SftpFileContentReadResult:
    content: bytes | None = None
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
    remote_read_performed: bool = False
    content_read_count: int = 0
    sftp_session_closed: bool = False
    credential_persisted: bool = False
    session_persisted: bool = False
    raw_response_persisted: bool = False
    remote_content_persisted: bool = False
    remote_content_returned: bool = False
    remote_content_logged: bool = False
    content_parsed: bool = False
    content_extracted: bool = False
    remote_list_performed: bool = False
    remote_stat_performed: bool = False
    remote_write_performed: bool = False
    remote_rename_performed: bool = False
    remote_delete_performed: bool = False
    remote_mkdir_performed: bool = False
    remote_chmod_performed: bool = False
    remote_chown_performed: bool = False
    remote_touch_performed: bool = False
    command_executed: bool = False


class SftpFileContentReadAdapter(Protocol):
    adapter_kind: str

    def read_content(self, request: SftpFileContentReadRequest) -> SftpFileContentReadResult: ...


_READ_ADAPTER: SftpFileContentReadAdapter | None = None


def register_external_document_source_sftp_file_content_read_adapter(adapter: SftpFileContentReadAdapter) -> None:
    global _READ_ADAPTER
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_ADAPTER_KIND.fullmatch(adapter_kind):
        raise ValueError("SFTP file content read adapter kind is invalid")
    _READ_ADAPTER = adapter


def clear_external_document_source_sftp_file_content_read_adapter() -> None:
    global _READ_ADAPTER
    _READ_ADAPTER = None


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
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _normalize_adapter_kind(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_ADAPTER_KIND.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError("SFTP file content read adapter kind is invalid")
    return normalized


def _effective_remote_path(root: str, relative_path: str) -> str:
    if root == "/":
        return "/" + relative_path
    return root.rstrip("/") + "/" + relative_path


def _scope_hash(*, listing, entry, adapter_kind: str, request_key: str) -> str:
    return _canonical_hash({
        "organization_id": str(listing.organization_id),
        "profile_id": str(listing.profile_id),
        "directory_listing_id": str(listing.id),
        "listing_scope_hash": listing.scope_hash,
        "listing_request_hash": listing.request_hash,
        "listing_result_hash": listing.result_hash,
        "listing_items_hash": listing.items_hash,
        "listing_entry_id": str(entry.id),
        "listing_entry_hash": entry.entry_hash,
        "credential_reference_binding_id": str(listing.credential_reference_binding_id),
        "locator_hash": listing.locator_hash,
        "authentication_kind": listing.authentication_kind,
        "reference_backend": listing.reference_backend,
        "destination_hostname": listing.destination_hostname,
        "destination_port": listing.destination_port,
        "pinned_host_key_fingerprint": listing.pinned_host_key_fingerprint,
        "remote_root_path_hash": listing.remote_root_path_hash,
        "read_adapter_kind": adapter_kind,
        "request_key": request_key,
        "read_limit": 1,
        "max_content_bytes": MAX_SFTP_CONTENT_PROOF_BYTES,
    })


def _requested_safety() -> dict:
    return {
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
        "remote_content_transiently_observed": False,
        "remote_read_performed": False,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _completed_safety() -> dict:
    return {
        "credential_reference_stored": True,
        "secret_resolution_performed": True,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": True,
        "authentication_performed": True,
        "authentication_succeeded": True,
        "sftp_session_opened": True,
        "sftp_session_closed": True,
        "remote_content_transiently_observed": True,
        "remote_read_performed": True,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _request_hash(row: ExternalDocumentSourceSftpFileContentProof) -> str:
    return _canonical_hash({
        "proof_id": str(row.id),
        "scope_hash": row.scope_hash,
        "requested_by_id": str(row.requested_by_id),
        "request_reason": row.request_reason,
        "requested_at": _iso(row.requested_at),
        **_requested_safety(),
    })


def _result_hash(row: ExternalDocumentSourceSftpFileContentProof) -> str:
    return _canonical_hash({
        "proof_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "completed_at": _iso(row.completed_at),
        "result_status": row.result_status,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        **_completed_safety(),
    })


def _receipt_hash(receipt: ExternalDocumentSourceSftpFileContentProofReceipt) -> str:
    return _canonical_hash({
        "organization_id": str(receipt.organization_id),
        "proof_id": str(receipt.proof_id),
        "sequence_number": receipt.sequence_number,
        "event_type": receipt.event_type,
        "status_after": receipt.status_after,
        "actor_id": str(receipt.actor_id),
        "occurred_at": _iso(receipt.occurred_at),
        "reason": receipt.reason,
        "scope_hash": receipt.scope_hash,
        "decision_hash": receipt.decision_hash,
        "prior_receipt_hash": receipt.prior_receipt_hash,
        **(_completed_safety() if receipt.event_type == "completed" else _requested_safety()),
    })


def _receipts(db: Session, row: ExternalDocumentSourceSftpFileContentProof):
    return db.scalars(
        select(ExternalDocumentSourceSftpFileContentProofReceipt)
        .where(ExternalDocumentSourceSftpFileContentProofReceipt.proof_id == row.id)
        .order_by(ExternalDocumentSourceSftpFileContentProofReceipt.sequence_number.asc())
    ).all()


def _append_receipts(db: Session, row: ExternalDocumentSourceSftpFileContentProof) -> None:
    requested = ExternalDocumentSourceSftpFileContentProofReceipt(
        organization_id=row.organization_id,
        proof_id=row.id,
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
        **_requested_safety(),
    )
    requested.receipt_hash = _receipt_hash(requested)
    completed = ExternalDocumentSourceSftpFileContentProofReceipt(
        organization_id=row.organization_id,
        proof_id=row.id,
        sequence_number=2,
        event_type="completed",
        status_after="read_verified",
        actor_id=row.requested_by_id,
        occurred_at=row.completed_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=row.result_hash,
        prior_receipt_hash=requested.receipt_hash,
        receipt_hash="0" * 64,
        **_completed_safety(),
    )
    completed.receipt_hash = _receipt_hash(completed)
    db.add_all([requested, completed])


def _load_listing_and_entry(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    listing_id: UUID,
    entry_id: UUID,
    for_update: bool,
):
    stmt = select(ExternalDocumentSourceSftpDirectoryListing).where(
        ExternalDocumentSourceSftpDirectoryListing.id == listing_id,
        ExternalDocumentSourceSftpDirectoryListing.organization_id == organization_id,
        ExternalDocumentSourceSftpDirectoryListing.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    listing = db.scalar(stmt)
    if listing is None:
        raise ExternalDocumentSourceNotFoundError("SFTP directory listing not found")
    _ensure_listing_integrity(db, listing)
    if listing.result_status != "listed" or listing.items_hash is None:
        raise ExternalDocumentSourceConflictError("SFTP file content proof requires an exact successful Phase 17.6-H listing")

    entry_stmt = select(ExternalDocumentSourceSftpDirectoryListingEntry).where(
        ExternalDocumentSourceSftpDirectoryListingEntry.id == entry_id,
        ExternalDocumentSourceSftpDirectoryListingEntry.organization_id == organization_id,
        ExternalDocumentSourceSftpDirectoryListingEntry.listing_id == listing_id,
    )
    if for_update:
        entry_stmt = entry_stmt.with_for_update()
    entry = db.scalar(entry_stmt)
    if entry is None:
        raise ExternalDocumentSourceNotFoundError("SFTP directory listing entry not found")
    if entry.entry_kind != "file":
        raise ExternalDocumentSourceConflictError("Only exact Phase 17.6-H file entries are eligible for content proof")
    return listing, entry


def _active_binding_and_profile(db: Session, listing: ExternalDocumentSourceSftpDirectoryListing):
    binding = get_external_document_source_sftp_credential_reference(
        db,
        organization_id=listing.organization_id,
        profile_id=listing.profile_id,
        binding_id=listing.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("SFTP credential reference is not active")
    if (
        binding.id != listing.credential_reference_binding_id
        or binding.locator_hash != listing.locator_hash
        or binding.authentication_kind != listing.authentication_kind
        or binding.reference_backend != listing.reference_backend
    ):
        raise ExternalDocumentSourceConflictError("SFTP file content proof credential lineage drifted")

    profile = get_external_document_source_profile(
        db,
        organization_id=listing.organization_id,
        profile_id=listing.profile_id,
    )
    normalized = normalize_provider_config("sftp", profile.normalized_config)
    if (
        profile.status != "active"
        or profile.provider_kind != "sftp"
        or normalized != profile.normalized_config
        or normalized["access_mode"] != "read_only"
        or profile.profile_hash != listing.profile_hash
        or normalized["hostname"] != listing.destination_hostname
        or normalized["port"] != listing.destination_port
        or normalized["host_key_fingerprint"] != listing.pinned_host_key_fingerprint
        or _canonical_hash({"remote_root_path": normalized["remote_root_path"]}) != listing.remote_root_path_hash
    ):
        raise ExternalDocumentSourceConflictError("SFTP file content proof profile/destination lineage drifted")
    return binding, normalized


def _validate_adapter_result(
    result: SftpFileContentReadResult,
    *,
    expected_auth_kind: str,
    declared_byte_size: int | None,
) -> tuple[bytes, str, str]:
    if not isinstance(result, SftpFileContentReadResult):
        raise ExternalDocumentSourceConflictError("SFTP file content read failed")

    if (
        result.credential_persisted
        or result.session_persisted
        or result.raw_response_persisted
        or result.remote_content_persisted
        or result.remote_content_returned
        or result.remote_content_logged
        or result.content_parsed
        or result.content_extracted
        or result.remote_list_performed
        or result.remote_stat_performed
        or result.remote_write_performed
        or result.remote_rename_performed
        or result.remote_delete_performed
        or result.remote_mkdir_performed
        or result.remote_chmod_performed
        or result.remote_chown_performed
        or result.remote_touch_performed
        or result.command_executed
    ):
        raise ExternalDocumentSourceConflictError("SFTP file content read adapter violated the bounded read-only boundary")

    if result.failure_code is not None:
        raise ExternalDocumentSourceConflictError("SFTP file content read failed")
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
        or not result.remote_read_performed
        or result.content_read_count != 1
        or not result.sftp_session_closed
    ):
        raise ExternalDocumentSourceConflictError("SFTP file content read adapter result is invalid")
    if not isinstance(result.content, bytes):
        raise ExternalDocumentSourceConflictError("SFTP file content read adapter returned invalid content")
    if len(result.content) > MAX_SFTP_CONTENT_PROOF_BYTES:
        raise ExternalDocumentSourceConflictError("SFTP file content exceeds the Phase 17.6-I byte bound")
    if declared_byte_size is not None and len(result.content) != declared_byte_size:
        raise ExternalDocumentSourceConflictError("SFTP file content byte count does not match Phase 17.6-H metadata")
    return result.content, result.authentication_method, result.latency_class


def _ensure_integrity(db: Session, row: ExternalDocumentSourceSftpFileContentProof) -> None:
    listing, entry = _load_listing_and_entry(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        listing_id=row.directory_listing_id,
        entry_id=row.listing_entry_id,
        for_update=False,
    )
    binding, _normalized = _active_binding_and_profile(db, listing)

    if (
        row.provider_kind != "sftp"
        or row.profile_hash != listing.profile_hash
        or row.session_activation_id != listing.session_activation_id
        or row.credential_reference_binding_id != listing.credential_reference_binding_id
        or row.credential_reference_binding_id != binding.id
        or row.locator_hash != listing.locator_hash
        or row.authentication_kind != listing.authentication_kind
        or row.reference_backend != listing.reference_backend
        or row.destination_hostname != listing.destination_hostname
        or row.destination_port != listing.destination_port
        or row.pinned_host_key_fingerprint != listing.pinned_host_key_fingerprint
        or row.remote_root_path_hash != listing.remote_root_path_hash
        or row.listing_scope_hash != listing.scope_hash
        or row.listing_request_hash != listing.request_hash
        or row.listing_result_hash != listing.result_hash
        or row.listing_items_hash != listing.items_hash
        or row.listing_entry_hash != entry.entry_hash
        or row.declared_byte_size != entry.byte_size
        or row.read_limit != 1
        or row.max_content_bytes != MAX_SFTP_CONTENT_PROOF_BYTES
        or row.result_status != "read_verified"
        or row.authentication_method not in _ALLOWED_AUTH_METHODS
        or row.latency_class not in _ALLOWED_LATENCY_CLASSES
        or not _HEX_64.fullmatch(row.content_sha256)
        or row.content_byte_count < 0
        or row.content_byte_count > MAX_SFTP_CONTENT_PROOF_BYTES
        or (row.declared_byte_size is not None and row.content_byte_count != row.declared_byte_size)
    ):
        raise ExternalDocumentSourceConflictError("SFTP file content proof lineage or result integrity failed")

    for field, expected in _completed_safety().items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError("SFTP file content proof safety boundary integrity failed")

    expected_scope = _scope_hash(listing=listing, entry=entry, adapter_kind=row.read_adapter_kind, request_key=row.request_key)
    if row.scope_hash != expected_scope or row.request_hash != _request_hash(row) or row.result_hash != _result_hash(row):
        raise ExternalDocumentSourceConflictError("SFTP file content proof hash integrity failed")
    if _aware(row.completed_at) < _aware(row.requested_at):
        raise ExternalDocumentSourceConflictError("SFTP file content proof timestamps drifted")

    receipts = _receipts(db, row)
    if len(receipts) != 2:
        raise ExternalDocumentSourceConflictError("SFTP file content proof receipt chain is incomplete")
    expected_receipts = (
        (1, "requested", "requested", row.requested_at, row.request_hash, None, _requested_safety()),
        (2, "completed", "read_verified", row.completed_at, row.result_hash, receipts[0].receipt_hash, _completed_safety()),
    )
    for receipt, facts in zip(receipts, expected_receipts, strict=True):
        seq, event, status_after, at, decision_hash, prior, safety = facts
        if (
            receipt.sequence_number != seq
            or receipt.event_type != event
            or receipt.status_after != status_after
            or receipt.actor_id != row.requested_by_id
            or _aware(receipt.occurred_at) != _aware(at)
            or receipt.reason != row.request_reason
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError("SFTP file content proof receipt integrity failed")
        for field, expected in safety.items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("SFTP file content proof receipt safety integrity failed")


def create_external_document_source_sftp_file_content_proof(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    directory_listing_id: UUID,
    listing_entry_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(select(ExternalDocumentSourceSftpFileContentProof).where(
        ExternalDocumentSourceSftpFileContentProof.listing_entry_id == listing_entry_id
    ))
    if existing is not None:
        if existing.organization_id != organization_id or existing.profile_id != profile_id or existing.directory_listing_id != directory_listing_id:
            raise ExternalDocumentSourceNotFoundError("SFTP directory listing entry not found")
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP file content proof")
        return existing, "unchanged"

    key_collision = db.scalar(select(ExternalDocumentSourceSftpFileContentProof).where(
        ExternalDocumentSourceSftpFileContentProof.organization_id == organization_id,
        ExternalDocumentSourceSftpFileContentProof.profile_id == profile_id,
        ExternalDocumentSourceSftpFileContentProof.request_key == normalized_key,
    ))
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP file content proof request_key")

    listing, entry = _load_listing_and_entry(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        listing_id=directory_listing_id,
        entry_id=listing_entry_id,
        for_update=True,
    )
    if entry.byte_size is not None and entry.byte_size > MAX_SFTP_CONTENT_PROOF_BYTES:
        raise ExternalDocumentSourceConflictError("Phase 17.6-H file exceeds the Phase 17.6-I declared-size byte bound")

    existing = db.scalar(select(ExternalDocumentSourceSftpFileContentProof).where(
        ExternalDocumentSourceSftpFileContentProof.listing_entry_id == listing_entry_id
    ))
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for SFTP file content proof")
        return existing, "unchanged"

    binding, normalized_config = _active_binding_and_profile(db, listing)
    adapter = _READ_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError("SFTP file content read adapter is unavailable")
    adapter_kind = _normalize_adapter_kind(adapter.adapter_kind)

    requested_at = _aware(now or _utc_now())
    request = SftpFileContentReadRequest(
        hostname=listing.destination_hostname,
        port=listing.destination_port,
        username=normalized_config["username"],
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
        remote_root_path=normalized_config["remote_root_path"],
        entry_relative_path=entry.relative_path,
        effective_remote_path=_effective_remote_path(normalized_config["remote_root_path"], entry.relative_path),
    )
    try:
        transient_result = adapter.read_content(request)
    except Exception:
        raise ExternalDocumentSourceConflictError("SFTP file content read failed") from None
    try:
        content, authentication_method, latency_class = _validate_adapter_result(
            transient_result,
            expected_auth_kind=binding.authentication_kind,
            declared_byte_size=entry.byte_size,
        )
        content_sha256 = hashlib.sha256(content).hexdigest()
        content_byte_count = len(content)
        del content
    finally:
        try:
            del transient_result
        except UnboundLocalError:
            pass

    completed_at = max(requested_at, _utc_now())
    scope_hash = _scope_hash(listing=listing, entry=entry, adapter_kind=adapter_kind, request_key=normalized_key)
    row = ExternalDocumentSourceSftpFileContentProof(
        organization_id=organization_id,
        profile_id=profile_id,
        directory_listing_id=listing.id,
        listing_entry_id=entry.id,
        session_activation_id=listing.session_activation_id,
        credential_reference_binding_id=listing.credential_reference_binding_id,
        provider_kind="sftp",
        profile_hash=listing.profile_hash,
        locator_hash=listing.locator_hash,
        authentication_kind=listing.authentication_kind,
        reference_backend=listing.reference_backend,
        destination_hostname=listing.destination_hostname,
        destination_port=listing.destination_port,
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        remote_root_path_hash=listing.remote_root_path_hash,
        listing_scope_hash=listing.scope_hash,
        listing_request_hash=listing.request_hash,
        listing_result_hash=listing.result_hash,
        listing_items_hash=listing.items_hash,
        listing_entry_hash=entry.entry_hash,
        declared_byte_size=entry.byte_size,
        read_adapter_kind=adapter_kind,
        read_limit=1,
        max_content_bytes=MAX_SFTP_CONTENT_PROOF_BYTES,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        completed_at=completed_at,
        result_status="read_verified",
        authentication_method=authentication_method,
        latency_class=latency_class,
        content_sha256=content_sha256,
        content_byte_count=content_byte_count,
        result_hash="0" * 64,
        **_completed_safety(),
    )
    row.request_hash = _request_hash(row)
    row.result_hash = _result_hash(row)
    db.add(row)
    db.flush()
    _append_receipts(db, row)
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_file_content_proof(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    proof_id: UUID,
):
    row = db.scalar(select(ExternalDocumentSourceSftpFileContentProof).where(
        ExternalDocumentSourceSftpFileContentProof.id == proof_id,
        ExternalDocumentSourceSftpFileContentProof.organization_id == organization_id,
        ExternalDocumentSourceSftpFileContentProof.profile_id == profile_id,
    ))
    if row is None:
        raise ExternalDocumentSourceNotFoundError("SFTP file content proof not found")
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_file_content_proof_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    proof_id: UUID,
):
    row = get_external_document_source_sftp_file_content_proof(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        proof_id=proof_id,
    )
    return _receipts(db, row)
