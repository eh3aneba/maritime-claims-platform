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
)
from app.modules.external_document_sources.sftp_change_detection_models import (
    MAX_SFTP_METADATA_BYTE_SIZE,
    ExternalDocumentSourceSftpChangeDetection,
    ExternalDocumentSourceSftpChangeDetectionReceipt,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_checkpoint_service import (
    _ensure_integrity as _ensure_checkpoint_integrity,
)
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
    ExternalDocumentSourceSftpDirectoryListingEntry,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    _effective_remote_path,
    _ensure_integrity as _ensure_directory_listing_integrity,
    _load_verified_lineage,
)

_SAFE_ADAPTER_KIND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OBSERVATION_OPERATION_KIND = "sftp_exact_file_metadata_stat_v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_AUTH_METHODS = frozenset({"password", "public_key"})
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_ALLOWED_FAILURE_CODES = frozenset({
    "not_found",
    "credential_resolution_failed",
    "credential_unavailable",
    "connection_failed",
    "connection_timeout",
    "host_key_revalidation_failed",
    "authentication_failed",
    "authentication_timeout",
    "sftp_subsystem_activation_failed",
    "stat_failed",
    "stat_timeout",
    "permission_denied",
    "path_policy_violation",
    "symlink_escape_detected",
    "invalid_adapter_result",
})
_FALSE_FIELDS = (
    "credential_stored", "session_stored", "remote_content_transiently_observed", "remote_list_performed", "remote_read_performed",
    "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
    "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
    "remote_touch_performed", "command_executed", "storage_read_performed",
    "storage_write_performed", "storage_delete_performed", "storage_copy_performed", "checkpoint_advanced", "subscription_created",
    "raw_response_stored", "remote_content_stored", "remote_content_returned",
    "remote_content_logged", "content_parsed", "content_extracted",
    "evidence_admitted", "document_created", "processing_enqueued",
    "ai_executed", "claim_mutated",
)


@dataclass(frozen=True)
class SftpExactFileMetadataRequest:
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
    connect_timeout_seconds: int = 5
    authentication_timeout_seconds: int = 5
    stat_timeout_seconds: int = 7
    total_timeout_seconds: int = 17
    max_connection_attempts: int = 1
    max_authentication_attempts: int = 1
    max_stat_attempts: int = 1
    allow_private_destinations: bool = False
    allow_redirects: bool = False
    allow_proxy_retargeting: bool = False
    read_only_intent: bool = True
    follow_symlinks: bool = False


@dataclass(frozen=True)
class SftpExactFileMetadataResult:
    found: bool = False
    failure_code: str | None = None
    entry_kind: str | None = None
    byte_size: int | None = None
    modified_at: datetime | None = None
    metadata_id_hash: str | None = None
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
    remote_stat_performed: bool = False
    sftp_session_closed: bool = False
    credential_persisted: bool = False
    session_persisted: bool = False
    raw_response_persisted: bool = False
    remote_list_performed: bool = False
    remote_read_performed: bool = False
    remote_write_performed: bool = False
    remote_rename_performed: bool = False
    remote_delete_performed: bool = False
    remote_mkdir_performed: bool = False
    remote_chmod_performed: bool = False
    remote_chown_performed: bool = False
    remote_touch_performed: bool = False
    command_executed: bool = False
    symlink_escape_detected: bool = False


class SftpExactFileMetadataAdapter(Protocol):
    adapter_kind: str

    def stat_metadata(
        self,
        request: SftpExactFileMetadataRequest,
    ) -> SftpExactFileMetadataResult: ...


_METADATA_ADAPTER: SftpExactFileMetadataAdapter | None = None


def register_external_document_source_sftp_exact_file_metadata_adapter(
    adapter: SftpExactFileMetadataAdapter,
) -> None:
    kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(kind, str) or not _SAFE_ADAPTER_KIND.fullmatch(kind):
        raise ValueError("SFTP exact-file metadata adapter kind is invalid")
    global _METADATA_ADAPTER
    _METADATA_ADAPTER = adapter


def clear_external_document_source_sftp_exact_file_metadata_adapter() -> None:
    global _METADATA_ADAPTER
    _METADATA_ADAPTER = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


def _canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _normalize_text(
    value: str,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(
            f"{field} contains an invalid character"
        )
    return normalized


def _relative_path_hash(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()


def _observation_policy_hash() -> str:
    return _canonical_hash({
        "operation_kind": _OBSERVATION_OPERATION_KIND,
        "connect_timeout_seconds": 5,
        "authentication_timeout_seconds": 5,
        "stat_timeout_seconds": 7,
        "total_timeout_seconds": 17,
        "max_connection_attempts": 1,
        "max_authentication_attempts": 1,
        "max_stat_attempts": 1,
        "allow_private_destinations": False,
        "allow_redirects": False,
        "allow_proxy_retargeting": False,
        "read_only_intent": True,
        "follow_symlinks": False,
    })


def _safety(completed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "upstream_checkpoint_completed": True,
        "secret_resolution_performed": completed,
        "credential_stored": False,
        "provider_network_performed": completed,
        "ssh_transport_performed": completed,
        "host_key_verification_performed": completed,
        "host_key_verified": completed,
        "authentication_performed": completed,
        "authentication_succeeded": completed,
        "sftp_session_opened": completed,
        "sftp_session_closed": completed,
        "exact_item_metadata_read_performed": completed,
        "change_detection_completed": completed,
        "remote_stat_performed": completed,
        **{field: False for field in _FALSE_FIELDS},
    }


def _load_baseline(
    db: Session,
    checkpoint: ExternalDocumentSourceSftpCheckpoint,
):
    listing = db.scalar(
        select(ExternalDocumentSourceSftpDirectoryListing).where(
            ExternalDocumentSourceSftpDirectoryListing.id
            == checkpoint.directory_listing_id,
            ExternalDocumentSourceSftpDirectoryListing.organization_id
            == checkpoint.organization_id,
            ExternalDocumentSourceSftpDirectoryListing.profile_id
            == checkpoint.profile_id,
        )
    )
    if listing is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint directory-listing lineage is missing"
        )
    _ensure_directory_listing_integrity(db, listing)
    if listing.result_status != "listed":
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint requires a successful Phase 17.6-H listing"
        )

    entry = db.scalar(
        select(ExternalDocumentSourceSftpDirectoryListingEntry).where(
            ExternalDocumentSourceSftpDirectoryListingEntry.id
            == checkpoint.listing_entry_id,
            ExternalDocumentSourceSftpDirectoryListingEntry.organization_id
            == checkpoint.organization_id,
            ExternalDocumentSourceSftpDirectoryListingEntry.listing_id
            == listing.id,
        )
    )
    if entry is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint file-entry lineage is missing"
        )
    if (
        entry.entry_hash != checkpoint.listing_entry_hash
        or entry.entry_kind != "file"
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint file-entry lineage drifted"
        )

    activation, binding, normalized = _load_verified_lineage(
        db,
        organization_id=checkpoint.organization_id,
        profile_id=checkpoint.profile_id,
        activation_id=listing.session_activation_id,
        for_update=False,
    )
    if (
        listing.credential_reference_binding_id != binding.id
        or checkpoint.profile_hash != listing.profile_hash
        or checkpoint.profile_hash != activation.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint active profile/credential lineage drifted"
        )
    return listing, entry, binding, normalized


def _scope_hash(
    checkpoint: ExternalDocumentSourceSftpCheckpoint,
    entry: ExternalDocumentSourceSftpDirectoryListingEntry,
    binding,
    *,
    adapter_kind: str,
    request_key: str,
) -> str:
    return _canonical_hash({
        "organization_id": str(checkpoint.organization_id),
        "profile_id": str(checkpoint.profile_id),
        "checkpoint_id": str(checkpoint.id),
        "checkpoint_state_hash": checkpoint.checkpoint_state_hash,
        "checkpoint_completion_hash": checkpoint.completion_hash,
        "directory_listing_id": str(checkpoint.directory_listing_id),
        "listing_entry_id": str(checkpoint.listing_entry_id),
        "baseline_entry_hash": entry.entry_hash,
        "baseline_relative_path_hash": _relative_path_hash(entry.relative_path),
        "credential_reference_binding_id": str(binding.id),
        "locator_hash": binding.locator_hash,
        "observation_operation_kind": _OBSERVATION_OPERATION_KIND,
        "observation_adapter_kind": adapter_kind,
        "observation_policy_hash": _observation_policy_hash(),
        "request_key": request_key,
        "observation_limit": 1,
        "content_read_authorized": False,
        "directory_list_authorized": False,
        "checkpoint_advance_authorized": False,
    })


def _request_hash(row: ExternalDocumentSourceSftpChangeDetection) -> str:
    return _canonical_hash({
        "execution_id": str(row.id),
        "scope_hash": row.scope_hash,
        "requested_by_id": str(row.requested_by_id),
        "request_reason": row.request_reason,
        "requested_at": _iso(row.requested_at),
        **_safety(False),
    })


def _observed_projection_hash(
    *,
    entry_kind: str,
    byte_size: int,
    modified_at: datetime | None,
    metadata_id_hash: str | None,
) -> str:
    return _canonical_hash({
        "entry_kind": entry_kind,
        "byte_size": byte_size,
        "modified_at": _iso(modified_at),
        "metadata_id_hash": metadata_id_hash,
    })


def _completion_hash(row: ExternalDocumentSourceSftpChangeDetection) -> str:
    return _canonical_hash({
        "execution_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "result_status": row.result_status,
        "observed_projection_hash": row.observed_projection_hash,
        "observed_entry_kind": row.observed_entry_kind,
        "observed_byte_size": row.observed_byte_size,
        "observed_modified_at": _iso(row.observed_modified_at),
        "observed_metadata_id_hash": row.observed_metadata_id_hash,
        "changed_dimensions": row.changed_dimensions,
        "authentication_method": row.authentication_method,
        "latency_class": row.latency_class,
        "completed_at": _iso(row.completed_at),
        **_safety(True),
    })


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpChangeDetectionReceipt,
) -> str:
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
        **_safety(receipt.event_type == "completed"),
    })


def _receipts(
    db: Session,
    row: ExternalDocumentSourceSftpChangeDetection,
):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpChangeDetectionReceipt)
            .where(
                ExternalDocumentSourceSftpChangeDetectionReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpChangeDetectionReceipt.execution_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpChangeDetectionReceipt.sequence_number.asc()
            )
        ).all()
    )


def _append_receipts(
    db: Session,
    row: ExternalDocumentSourceSftpChangeDetection,
) -> None:
    requested = ExternalDocumentSourceSftpChangeDetectionReceipt(
        organization_id=row.organization_id,
        execution_id=row.id,
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
        **_safety(False),
    )
    requested.receipt_hash = _receipt_hash(requested)
    completed = ExternalDocumentSourceSftpChangeDetectionReceipt(
        organization_id=row.organization_id,
        execution_id=row.id,
        sequence_number=2,
        event_type="completed",
        status_after=row.result_status,
        actor_id=row.requested_by_id,
        occurred_at=row.completed_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=row.completion_hash,
        prior_receipt_hash=requested.receipt_hash,
        receipt_hash="0" * 64,
        **_safety(True),
    )
    completed.receipt_hash = _receipt_hash(completed)
    db.add_all([requested, completed])


def _validate_adapter_result(
    result: SftpExactFileMetadataResult,
    *,
    expected_auth_kind: str,
) -> dict:
    if not isinstance(result, SftpExactFileMetadataResult):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter returned an invalid result"
        )
    if (
        result.credential_persisted
        or result.session_persisted
        or result.raw_response_persisted
        or result.remote_list_performed
        or result.remote_read_performed
        or result.remote_write_performed
        or result.remote_rename_performed
        or result.remote_delete_performed
        or result.remote_mkdir_performed
        or result.remote_chmod_performed
        or result.remote_chown_performed
        or result.remote_touch_performed
        or result.command_executed
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter violated the metadata-only boundary"
        )
    if result.symlink_escape_detected:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata observation detected a symlink/path escape"
        )
    if result.sftp_session_opened and not result.sftp_session_closed:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter did not prove immediate session closure"
        )
    expected_method = (
        "password" if expected_auth_kind == "password" else "public_key"
    )
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
        or not result.remote_stat_performed
        or not result.sftp_session_closed
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter did not prove the bounded stat lifecycle"
        )

    if result.failure_code is not None:
        failure = (
            result.failure_code
            if result.failure_code in _ALLOWED_FAILURE_CODES
            else "invalid_adapter_result"
        )
        if failure != "not_found":
            raise ExternalDocumentSourceConflictError(
                f"SFTP exact-file metadata observation failed: {failure}"
            )
        if (
            result.found
            or result.entry_kind is not None
            or result.byte_size is not None
            or result.modified_at is not None
            or result.metadata_id_hash is not None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP canonical not-found result included unsupported metadata"
            )
        return {
            "result_status": "missing",
            "authentication_method": result.authentication_method,
            "latency_class": result.latency_class,
            "observed_projection_hash": None,
            "observed_entry_kind": None,
            "observed_byte_size": None,
            "observed_modified_at": None,
            "observed_metadata_id_hash": None,
            "changed_dimensions": None,
        }

    if not result.found or result.entry_kind != "file":
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata observation did not return the exact file"
        )
    if (
        not isinstance(result.byte_size, int)
        or result.byte_size < 0
        or result.byte_size > MAX_SFTP_METADATA_BYTE_SIZE
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata observation returned an invalid byte size"
        )
    modified_at = (
        _aware(result.modified_at)
        if result.modified_at is not None
        else None
    )
    metadata_id_hash = result.metadata_id_hash
    if metadata_id_hash is not None and (
        not isinstance(metadata_id_hash, str)
        or not _HEX_64.fullmatch(metadata_id_hash)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata observation returned an invalid metadata identifier hash"
        )
    return {
        "result_status": None,
        "authentication_method": result.authentication_method,
        "latency_class": result.latency_class,
        "observed_projection_hash": _observed_projection_hash(
            entry_kind="file",
            byte_size=result.byte_size,
            modified_at=modified_at,
            metadata_id_hash=metadata_id_hash,
        ),
        "observed_entry_kind": "file",
        "observed_byte_size": result.byte_size,
        "observed_modified_at": modified_at,
        "observed_metadata_id_hash": metadata_id_hash,
        "changed_dimensions": None,
    }


def _classify(
    checkpoint: ExternalDocumentSourceSftpCheckpoint,
    entry: ExternalDocumentSourceSftpDirectoryListingEntry,
    observed: dict,
) -> dict:
    if observed["result_status"] == "missing":
        return observed

    dimensions: list[str] = []
    if observed["observed_byte_size"] != checkpoint.content_byte_count:
        dimensions.append("byte_size")
    if entry.modified_at is not None:
        if observed["observed_modified_at"] != _aware(entry.modified_at):
            dimensions.append("modified_at")
    if entry.metadata_id_hash is not None:
        if observed["observed_metadata_id_hash"] != entry.metadata_id_hash:
            dimensions.append("metadata_id")

    observed["result_status"] = "changed" if dimensions else "unchanged"
    observed["changed_dimensions"] = ",".join(dimensions) if dimensions else None
    return observed


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpChangeDetection,
) -> None:
    checkpoint = db.scalar(
        select(ExternalDocumentSourceSftpCheckpoint).where(
            ExternalDocumentSourceSftpCheckpoint.id == row.checkpoint_id,
            ExternalDocumentSourceSftpCheckpoint.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpCheckpoint.profile_id == row.profile_id,
        )
    )
    if checkpoint is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP change-detection checkpoint lineage is missing"
        )
    _ensure_checkpoint_integrity(db, checkpoint)
    listing, entry, binding, _normalized = _load_baseline(db, checkpoint)

    if (
        row.directory_listing_id != listing.id
        or row.listing_entry_id != entry.id
        or row.credential_reference_binding_id != binding.id
        or row.provider_kind != "sftp"
        or row.profile_hash != checkpoint.profile_hash
        or row.checkpoint_state_hash != checkpoint.checkpoint_state_hash
        or row.checkpoint_completion_hash != checkpoint.completion_hash
        or row.baseline_entry_hash != entry.entry_hash
        or row.baseline_relative_path_hash
        != _relative_path_hash(entry.relative_path)
        or row.baseline_entry_kind != "file"
        or row.baseline_byte_size != checkpoint.content_byte_count
        or (
            row.baseline_modified_at is None
            and entry.modified_at is not None
        )
        or (
            row.baseline_modified_at is not None
            and entry.modified_at is None
        )
        or (
            row.baseline_modified_at is not None
            and _aware(row.baseline_modified_at) != _aware(entry.modified_at)
        )
        or row.baseline_metadata_id_hash != entry.metadata_id_hash
        or row.observation_operation_kind != _OBSERVATION_OPERATION_KIND
        or row.observation_policy_hash != _observation_policy_hash()
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP change-detection baseline lineage drifted"
        )

    expected_scope = _scope_hash(
        checkpoint,
        entry,
        binding,
        adapter_kind=row.observation_adapter_kind,
        request_key=row.request_key,
    )
    if (
        row.scope_hash != expected_scope
        or row.request_hash != _request_hash(row)
        or row.completion_hash != _completion_hash(row)
        or row.result_status not in {"unchanged", "changed", "missing"}
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP change-detection integrity failed"
        )

    if row.result_status == "missing":
        if any(
            value is not None
            for value in (
                row.observed_projection_hash,
                row.observed_entry_kind,
                row.observed_byte_size,
                row.observed_modified_at,
                row.observed_metadata_id_hash,
                row.changed_dimensions,
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP missing observation contains unexpected metadata"
            )
    else:
        if (
            row.observed_projection_hash is None
            or row.observed_entry_kind != "file"
            or row.observed_byte_size is None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP change observation metadata is incomplete"
            )
        expected_projection = _observed_projection_hash(
            entry_kind="file",
            byte_size=row.observed_byte_size,
            modified_at=row.observed_modified_at,
            metadata_id_hash=row.observed_metadata_id_hash,
        )
        if row.observed_projection_hash != expected_projection:
            raise ExternalDocumentSourceConflictError(
                "SFTP observed metadata projection integrity failed"
            )
        classified = _classify(
            checkpoint,
            entry,
            {
                "result_status": None,
                "observed_projection_hash": row.observed_projection_hash,
                "observed_entry_kind": row.observed_entry_kind,
                "observed_byte_size": row.observed_byte_size,
                "observed_modified_at": (
                    _aware(row.observed_modified_at)
                    if row.observed_modified_at is not None
                    else None
                ),
                "observed_metadata_id_hash": row.observed_metadata_id_hash,
                "changed_dimensions": None,
                "authentication_method": row.authentication_method,
                "latency_class": row.latency_class,
            },
        )
        if (
            row.result_status != classified["result_status"]
            or row.changed_dimensions != classified["changed_dimensions"]
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP change classification integrity failed"
            )

    if (
        row.authentication_method not in _ALLOWED_AUTH_METHODS
        or row.latency_class not in _ALLOWED_LATENCY_CLASSES
        or _aware(row.completed_at) < _aware(row.requested_at)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP change-detection bounded execution facts drifted"
        )
    for field, expected in _safety(True).items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP change-detection safety boundary drifted"
            )

    receipts = _receipts(db, row)
    if len(receipts) != 2:
        raise ExternalDocumentSourceConflictError(
            "SFTP change-detection receipt chain is incomplete"
        )
    expected_receipts = (
        (1, "requested", "requested", row.requested_at, row.request_hash, None, False),
        (
            2,
            "completed",
            row.result_status,
            row.completed_at,
            row.completion_hash,
            receipts[0].receipt_hash,
            True,
        ),
    )
    for receipt, facts in zip(receipts, expected_receipts, strict=True):
        seq, event, status_after, occurred, decision, prior, completed = facts
        if (
            receipt.sequence_number != seq
            or receipt.event_type != event
            or receipt.status_after != status_after
            or receipt.actor_id != row.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred)
            or receipt.reason != row.request_reason
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != decision
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP change-detection receipt integrity failed"
            )
        for field, expected_value in _safety(completed).items():
            if bool(getattr(receipt, field)) != expected_value:
                raise ExternalDocumentSourceConflictError(
                    "SFTP change-detection receipt safety boundary drifted"
                )


def execute_external_document_source_sftp_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    checkpoint_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        request_reason, field="reason", minimum=8, maximum=2000
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpChangeDetection).where(
            ExternalDocumentSourceSftpChangeDetection.organization_id
            == organization_id,
            ExternalDocumentSourceSftpChangeDetection.profile_id == profile_id,
            ExternalDocumentSourceSftpChangeDetection.checkpoint_id
            == checkpoint_id,
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
                "Conflicting replay for SFTP exact-file change detection"
            )
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceSftpChangeDetection).where(
            ExternalDocumentSourceSftpChangeDetection.organization_id
            == organization_id,
            ExternalDocumentSourceSftpChangeDetection.profile_id == profile_id,
            ExternalDocumentSourceSftpChangeDetection.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "Conflicting replay for SFTP exact-file change-detection request_key"
        )

    checkpoint = db.scalar(
        select(ExternalDocumentSourceSftpCheckpoint)
        .where(
            ExternalDocumentSourceSftpCheckpoint.id == checkpoint_id,
            ExternalDocumentSourceSftpCheckpoint.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCheckpoint.profile_id == profile_id,
        )
        .with_for_update()
    )
    if checkpoint is None:
        raise ExternalDocumentSourceNotFoundError(
            "Phase 17.6-K SFTP checkpoint not found"
        )
    _ensure_checkpoint_integrity(db, checkpoint)
    if (
        checkpoint.status != "completed"
        or checkpoint.result_status != "checkpoint_recorded"
        or checkpoint.checkpoint_generation != 1
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-K SFTP checkpoint is not eligible for change detection"
        )

    second = db.scalar(
        select(ExternalDocumentSourceSftpChangeDetection).where(
            ExternalDocumentSourceSftpChangeDetection.checkpoint_id
            == checkpoint.id
        )
    )
    if second is not None:
        _ensure_integrity(db, second)
        if (
            second.request_key != normalized_key
            or second.request_reason != normalized_reason
            or second.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP exact-file change detection"
            )
        return second, "unchanged"

    listing, entry, binding, normalized = _load_baseline(db, checkpoint)
    adapter = _METADATA_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter is unavailable"
        )
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_ADAPTER_KIND.fullmatch(
        adapter_kind
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter kind is invalid"
        )

    request = SftpExactFileMetadataRequest(
        hostname=listing.destination_hostname,
        port=listing.destination_port,
        username=normalized["username"],
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
        remote_root_path=normalized["remote_root_path"],
        entry_relative_path=entry.relative_path,
        effective_remote_path=_effective_remote_path(
            normalized["remote_root_path"],
            entry.relative_path,
        ),
    )
    try:
        raw_result = adapter.stat_metadata(request)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata observation failed"
        ) from None
    observed = _validate_adapter_result(
        raw_result,
        expected_auth_kind=binding.authentication_kind,
    )
    observed = _classify(checkpoint, entry, observed)

    requested_at = _aware(now or _utc_now())
    completed_at = max(requested_at, _utc_now())
    scope_hash = _scope_hash(
        checkpoint,
        entry,
        binding,
        adapter_kind=adapter_kind,
        request_key=normalized_key,
    )
    row = ExternalDocumentSourceSftpChangeDetection(
        id=uuid4(),
        organization_id=organization_id,
        profile_id=profile_id,
        checkpoint_id=checkpoint.id,
        directory_listing_id=listing.id,
        listing_entry_id=entry.id,
        credential_reference_binding_id=binding.id,
        provider_kind="sftp",
        profile_hash=checkpoint.profile_hash,
        checkpoint_state_hash=checkpoint.checkpoint_state_hash,
        checkpoint_completion_hash=checkpoint.completion_hash,
        baseline_entry_hash=entry.entry_hash,
        baseline_relative_path_hash=_relative_path_hash(entry.relative_path),
        baseline_entry_kind="file",
        baseline_byte_size=checkpoint.content_byte_count,
        baseline_modified_at=(
            _aware(entry.modified_at) if entry.modified_at is not None else None
        ),
        baseline_metadata_id_hash=entry.metadata_id_hash,
        observation_operation_kind=_OBSERVATION_OPERATION_KIND,
        observation_adapter_kind=adapter_kind,
        observation_policy_hash=_observation_policy_hash(),
        authentication_method=observed["authentication_method"],
        latency_class=observed["latency_class"],
        observed_projection_hash=observed["observed_projection_hash"],
        observed_entry_kind=observed["observed_entry_kind"],
        observed_byte_size=observed["observed_byte_size"],
        observed_modified_at=observed["observed_modified_at"],
        observed_metadata_id_hash=observed["observed_metadata_id_hash"],
        changed_dimensions=observed["changed_dimensions"],
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        result_status=observed["result_status"],
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        completed_at=completed_at,
        completion_hash="0" * 64,
        **_safety(True),
    )
    row.request_hash = _request_hash(row)
    row.completion_hash = _completion_hash(row)
    db.add(row)
    db.flush()
    _append_receipts(db, row)
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSftpChangeDetection).where(
            ExternalDocumentSourceSftpChangeDetection.id == execution_id,
            ExternalDocumentSourceSftpChangeDetection.organization_id
            == organization_id,
            ExternalDocumentSourceSftpChangeDetection.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP change-detection execution not found"
        )
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_change_detection_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    row = get_external_document_source_sftp_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, row)
