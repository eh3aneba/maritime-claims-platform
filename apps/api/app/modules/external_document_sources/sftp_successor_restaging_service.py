from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_change_detection_models import (
    ExternalDocumentSourceSftpChangeDetection,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    _ensure_integrity as _ensure_change_detection_integrity,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_checkpoint_service import (
    _ensure_integrity as _ensure_checkpoint_integrity,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
    _active_binding_and_profile,
    _effective_remote_path,
    _ensure_integrity as _ensure_file_content_proof_integrity,
    _load_listing_and_entry,
    _validate_adapter_result,
    get_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    _configured_store,
    _ensure_anchor_integrity as _ensure_quarantine_staging_integrity,
)
from app.modules.external_document_sources.sftp_successor_restaging_models import (
    MAX_SFTP_SUCCESSOR_BYTES,
    SFTP_SUCCESSOR_STORAGE_PURPOSE,
    ExternalDocumentSourceSftpSuccessorRestaging,
    ExternalDocumentSourceSftpSuccessorRestagingReceipt,
)


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_READ_OPERATION_KIND = "sftp_exact_file_content_read_v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_FALSE_FIELDS = (
    "credential_stored", "session_stored", "raw_response_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed",
    "content_extracted", "remote_list_performed", "remote_stat_performed",
    "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
    "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
    "remote_touch_performed", "command_executed", "storage_delete_performed",
    "storage_copy_performed", "checkpoint_advanced", "evidence_admitted",
    "document_created", "processing_enqueued", "ai_executed", "claim_mutated",
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


def _read_policy_hash() -> str:
    return _canonical_hash({
        "read_operation_kind": _READ_OPERATION_KIND,
        "max_content_bytes": MAX_SFTP_SUCCESSOR_BYTES,
        "max_chunk_bytes": 65536,
        "connect_timeout_seconds": 5,
        "authentication_timeout_seconds": 5,
        "read_timeout_seconds": 12,
        "total_timeout_seconds": 22,
        "max_connection_attempts": 1,
        "max_authentication_attempts": 1,
        "max_read_attempts": 1,
        "allow_private_destinations": False,
        "allow_redirects": False,
        "allow_proxy_retargeting": False,
        "read_only_intent": True,
        "exact_file_only": True,
        "follow_symlinks": False,
    })


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "upstream_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "successor_content_proof_completed": executed,
        "secret_resolution_performed": executed,
        "provider_network_performed": executed,
        "ssh_transport_performed": executed,
        "host_key_verification_performed": executed,
        "host_key_verified": executed,
        "authentication_performed": executed,
        "authentication_succeeded": executed,
        "sftp_session_opened": executed,
        "sftp_session_closed": executed,
        "remote_content_transiently_observed": executed,
        "remote_read_performed": executed,
        "storage_write_performed": executed,
        "storage_read_performed": executed,
        "storage_reconciliation_performed": executed,
        "durable_content_staged": executed,
        "remote_content_stored": executed,
        **{field: False for field in _FALSE_FIELDS},
    }


def _storage_key(
    restaging_id: UUID,
    organization_id: UUID,
    successor_generation: int,
) -> str:
    return (
        "external-sftp-content-quarantine-successor/"
        f"{organization_id}/{restaging_id}/generation-{successor_generation}"
    )


def _scope_hash(
    change: ExternalDocumentSourceSftpChangeDetection,
    checkpoint: ExternalDocumentSourceSftpCheckpoint,
    proof: ExternalDocumentSourceSftpFileContentProof,
    *,
    storage_backend_kind: str,
    storage_object_key_hash: str,
    successor_generation: int,
    request_key: str,
) -> str:
    return _canonical_hash({
        "organization_id": str(change.organization_id),
        "profile_id": str(change.profile_id),
        "change_detection_id": str(change.id),
        "change_scope_hash": change.scope_hash,
        "change_request_hash": change.request_hash,
        "change_completion_hash": change.completion_hash,
        "observed_projection_hash": change.observed_projection_hash,
        "observed_byte_size": change.observed_byte_size,
        "checkpoint_id": str(checkpoint.id),
        "checkpoint_state_hash": checkpoint.checkpoint_state_hash,
        "checkpoint_completion_hash": checkpoint.completion_hash,
        "predecessor_content_sha256": checkpoint.content_sha256,
        "predecessor_content_byte_count": checkpoint.content_byte_count,
        "file_content_proof_id": str(proof.id),
        "proof_result_hash": proof.result_hash,
        "listing_entry_hash": proof.listing_entry_hash,
        "read_operation_kind": _READ_OPERATION_KIND,
        "read_policy_hash": _read_policy_hash(),
        "read_adapter_kind": proof.read_adapter_kind,
        "successor_generation": successor_generation,
        "storage_backend_kind": storage_backend_kind,
        "storage_purpose": SFTP_SUCCESSOR_STORAGE_PURPOSE,
        "storage_object_key_hash": storage_object_key_hash,
        "request_key": request_key,
        "checkpoint_advance_authorized": False,
        "document_authorized": False,
        "evidence_authorized": False,
    })


def _request_hash(row: ExternalDocumentSourceSftpSuccessorRestaging) -> str:
    return _canonical_hash({
        "restaging_id": str(row.id),
        "scope_hash": row.scope_hash,
        "storage_object_key": row.storage_object_key,
        "requested_by_id": str(row.requested_by_id),
        "request_reason": row.request_reason,
        "requested_at": _iso(row.requested_at),
        **_base_safety(False),
    })


def _successor_content_proof_hash(
    row: ExternalDocumentSourceSftpSuccessorRestaging,
) -> str:
    if (
        row.successor_content_sha256 is None
        or row.successor_content_byte_count is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor content proof facts are incomplete"
        )
    return _canonical_hash({
        "restaging_id": str(row.id),
        "scope_hash": row.scope_hash,
        "change_completion_hash": row.change_completion_hash,
        "checkpoint_completion_hash": row.checkpoint_completion_hash,
        "read_operation_kind": row.read_operation_kind,
        "read_policy_hash": row.read_policy_hash,
        "read_adapter_kind": row.read_adapter_kind,
        "authentication_kind": row.authentication_kind,
        "successor_generation": row.successor_generation,
        "successor_content_sha256": row.successor_content_sha256,
        "successor_content_byte_count": row.successor_content_byte_count,
    })


def _completion_hash(row: ExternalDocumentSourceSftpSuccessorRestaging) -> str:
    if (
        row.status != "completed"
        or row.result_status != "successor_staged_verified"
        or row.completed_at is None
        or row.successor_content_sha256 is None
        or row.successor_content_byte_count is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging completion facts are incomplete"
        )
    return _canonical_hash({
        "restaging_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "result_status": row.result_status,
        "successor_generation": row.successor_generation,
        "successor_content_sha256": row.successor_content_sha256,
        "successor_content_byte_count": row.successor_content_byte_count,
        "successor_content_proof_hash": row.successor_content_proof_hash,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "stored_etag": row.stored_etag,
        "completed_at": _iso(row.completed_at),
        **_base_safety(True),
    })


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpSuccessorRestagingReceipt,
) -> str:
    return _canonical_hash({
        "organization_id": str(receipt.organization_id),
        "restaging_id": str(receipt.restaging_id),
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


def _receipts(
    db: Session,
    row: ExternalDocumentSourceSftpSuccessorRestaging,
):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpSuccessorRestagingReceipt)
            .where(
                ExternalDocumentSourceSftpSuccessorRestagingReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpSuccessorRestagingReceipt.restaging_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpSuccessorRestagingReceipt.sequence_number.asc()
            )
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceSftpSuccessorRestaging,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpSuccessorRestagingReceipt(
        organization_id=row.organization_id,
        restaging_id=row.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=row.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        receipt_hash="0" * 64,
        **_base_safety(event_type == "completed"),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _load_lineage(
    db: Session,
    row: ExternalDocumentSourceSftpSuccessorRestaging,
):
    change = db.scalar(
        select(ExternalDocumentSourceSftpChangeDetection).where(
            ExternalDocumentSourceSftpChangeDetection.id == row.change_detection_id,
            ExternalDocumentSourceSftpChangeDetection.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpChangeDetection.profile_id == row.profile_id,
        )
    )
    if change is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-L change-detection lineage is missing"
        )
    _ensure_change_detection_integrity(db, change)

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
            "Phase 17.6-K checkpoint lineage is missing"
        )
    _ensure_checkpoint_integrity(db, checkpoint)

    staging = db.scalar(
        select(ExternalDocumentSourceSftpQuarantineStaging).where(
            ExternalDocumentSourceSftpQuarantineStaging.id
            == row.quarantine_staging_id,
            ExternalDocumentSourceSftpQuarantineStaging.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpQuarantineStaging.profile_id
            == row.profile_id,
        )
    )
    if staging is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-J quarantine lineage is missing"
        )
    _ensure_quarantine_staging_integrity(db, staging, verify_storage=False)

    proof = db.scalar(
        select(ExternalDocumentSourceSftpFileContentProof).where(
            ExternalDocumentSourceSftpFileContentProof.id
            == row.file_content_proof_id,
            ExternalDocumentSourceSftpFileContentProof.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpFileContentProof.profile_id == row.profile_id,
        )
    )
    if proof is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-I content-proof lineage is missing"
        )
    _ensure_file_content_proof_integrity(db, proof)
    return change, checkpoint, staging, proof


def _verify_successor_object(
    store,
    row: ExternalDocumentSourceSftpSuccessorRestaging,
):
    try:
        metadata = store.head_object(storage_key=row.storage_object_key)
        digest = metadata.file_hash.lower()
        byte_count = metadata.file_size_bytes
        if (
            not _HEX_64.fullmatch(digest)
            or byte_count != row.observed_byte_size
            or byte_count < 0
            or byte_count > MAX_SFTP_SUCCESSOR_BYTES
            or digest == row.predecessor_content_sha256
        ):
            raise ExternalDocumentSourceConflictError(
                "Successor quarantine object does not match the changed-file observation"
            )
        payload = store.get_bytes(
            storage_key=row.storage_object_key,
            expected_sha256=digest,
        )
        if (
            len(payload) != byte_count
            or hashlib.sha256(payload).hexdigest() != digest
        ):
            raise ExternalDocumentSourceConflictError(
                "Successor quarantine object failed digest/size reconciliation"
            )
        del payload
        return metadata, digest, byte_count
    except (ObjectStorageNotFound, ExternalDocumentSourceConflictError):
        raise
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Governed SFTP successor quarantine verification failed"
        ) from None


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpSuccessorRestaging,
    *,
    verify_storage: bool,
) -> None:
    change, checkpoint, staging, proof = _load_lineage(db, row)
    if (
        change.result_status != "changed"
        or change.observed_projection_hash is None
        or change.observed_byte_size is None
        or row.checkpoint_id != change.checkpoint_id
        or row.checkpoint_id != checkpoint.id
        or row.quarantine_staging_id != checkpoint.quarantine_staging_id
        or row.quarantine_staging_id != staging.id
        or row.file_content_proof_id != checkpoint.file_content_proof_id
        or row.file_content_proof_id != proof.id
        or row.directory_listing_id != checkpoint.directory_listing_id
        or row.listing_entry_id != checkpoint.listing_entry_id
        or row.session_activation_id != staging.session_activation_id
        or row.credential_reference_binding_id
        != staging.credential_reference_binding_id
        or row.provider_kind != "sftp"
        or row.profile_hash != checkpoint.profile_hash
        or row.locator_hash != staging.locator_hash
        or row.authentication_kind != staging.authentication_kind
        or row.reference_backend != staging.reference_backend
        or row.destination_hostname != staging.destination_hostname
        or row.destination_port != staging.destination_port
        or row.pinned_host_key_fingerprint
        != staging.pinned_host_key_fingerprint
        or row.remote_root_path_hash != staging.remote_root_path_hash
        or row.checkpoint_state_hash != checkpoint.checkpoint_state_hash
        or row.checkpoint_completion_hash != checkpoint.completion_hash
        or row.predecessor_content_sha256 != checkpoint.content_sha256
        or row.predecessor_content_byte_count != checkpoint.content_byte_count
        or row.change_scope_hash != change.scope_hash
        or row.change_request_hash != change.request_hash
        or row.change_completion_hash != change.completion_hash
        or row.observed_projection_hash != change.observed_projection_hash
        or row.observed_byte_size != change.observed_byte_size
        or row.listing_entry_hash != checkpoint.listing_entry_hash
        or row.read_operation_kind != _READ_OPERATION_KIND
        or row.read_policy_hash != _read_policy_hash()
        or row.read_adapter_kind != proof.read_adapter_kind
        or row.successor_generation != checkpoint.checkpoint_generation + 1
        or row.storage_backend_kind != staging.storage_backend_kind
        or row.storage_purpose != SFTP_SUCCESSOR_STORAGE_PURPOSE
        or row.storage_object_key
        != _storage_key(row.id, row.organization_id, row.successor_generation)
        or row.storage_object_key_hash
        != hashlib.sha256(row.storage_object_key.encode("utf-8")).hexdigest()
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging lineage drifted"
        )
    if (
        row.observed_byte_size < 0
        or row.observed_byte_size > MAX_SFTP_SUCCESSOR_BYTES
    ):
        raise ExternalDocumentSourceConflictError(
            "Changed SFTP file exceeds the successor restaging byte bound"
        )

    expected_scope = _scope_hash(
        change,
        checkpoint,
        proof,
        storage_backend_kind=row.storage_backend_kind,
        storage_object_key_hash=row.storage_object_key_hash,
        successor_generation=row.successor_generation,
        request_key=row.request_key,
    )
    if row.scope_hash != expected_scope or row.request_hash != _request_hash(row):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging request integrity failed"
        )

    receipts = _receipts(db, row)
    if (
        not receipts
        or receipts[0].sequence_number != 1
        or receipts[0].event_type != "requested"
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging requested receipt is missing"
        )
    requested = receipts[0]
    if (
        requested.status_after != "requested"
        or requested.actor_id != row.requested_by_id
        or _aware(requested.occurred_at) != _aware(row.requested_at)
        or requested.reason != row.request_reason
        or requested.scope_hash != row.scope_hash
        or requested.decision_hash != row.request_hash
        or requested.prior_receipt_hash is not None
        or requested.receipt_hash != _receipt_hash(requested)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging requested receipt integrity failed"
        )
    for field, expected in _base_safety(False).items():
        if bool(getattr(requested, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP successor requested receipt safety boundary drifted"
            )

    if row.status == "requested":
        if (
            len(receipts) != 1
            or row.result_status is not None
            or row.completed_at is not None
            or row.completion_hash is not None
            or row.successor_content_sha256 is not None
            or row.successor_content_byte_count is not None
            or row.successor_content_proof_hash is not None
            or row.stored_etag is not None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP successor recovery-anchor lifecycle drifted"
            )
        for field, expected in _base_safety(False).items():
            if bool(getattr(row, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP successor recovery-anchor safety boundary drifted"
                )
        return

    if (
        row.status != "completed"
        or row.result_status != "successor_staged_verified"
        or row.completed_at is None
        or row.successor_content_sha256 is None
        or not _HEX_64.fullmatch(row.successor_content_sha256)
        or row.successor_content_sha256 == row.predecessor_content_sha256
        or row.successor_content_byte_count != row.observed_byte_size
        or row.successor_content_proof_hash != _successor_content_proof_hash(row)
        or row.completion_hash != _completion_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging completion integrity failed"
        )
    for field, expected in _base_safety(True).items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP successor completion safety boundary drifted"
            )
    if (
        len(receipts) != 2
        or receipts[1].event_type != "completed"
        or receipts[1].sequence_number != 2
        or receipts[1].status_after != "completed"
        or receipts[1].actor_id != row.requested_by_id
        or _aware(receipts[1].occurred_at) != _aware(row.completed_at)
        or receipts[1].reason != row.request_reason
        or receipts[1].scope_hash != row.scope_hash
        or receipts[1].decision_hash != row.completion_hash
        or receipts[1].prior_receipt_hash != receipts[0].receipt_hash
        or receipts[1].receipt_hash != _receipt_hash(receipts[1])
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor completed receipt integrity failed"
        )
    for field, expected in _base_safety(True).items():
        if bool(getattr(receipts[1], field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP successor completed receipt safety boundary drifted"
            )
    if _aware(row.completed_at) < _aware(row.requested_at):
        raise ExternalDocumentSourceConflictError(
            "SFTP successor restaging timestamps drifted"
        )
    if verify_storage:
        metadata, digest, byte_count = _verify_successor_object(store=_configured_store(), row=row)
        if (
            digest != row.successor_content_sha256
            or byte_count != row.successor_content_byte_count
            or metadata.etag != row.stored_etag
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP successor persisted storage facts drifted"
            )


def _complete_from_storage(
    db: Session,
    row: ExternalDocumentSourceSftpSuccessorRestaging,
    *,
    metadata,
    digest: str,
    byte_count: int,
    completed_at: datetime,
) -> None:
    row.status = "completed"
    row.result_status = "successor_staged_verified"
    row.successor_content_sha256 = digest
    row.successor_content_byte_count = byte_count
    row.successor_content_proof_hash = _successor_content_proof_hash(row)
    row.stored_etag = metadata.etag
    row.completed_at = completed_at
    for field, value in _base_safety(True).items():
        setattr(row, field, value)
    row.completion_hash = _completion_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="completed",
        actor_id=row.requested_by_id,
        occurred_at=completed_at,
        decision_hash=row.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, row, verify_storage=False)


def execute_external_document_source_sftp_successor_restaging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    change_detection_id: UUID,
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
    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ExternalDocumentSourceConflictError(
            "Governed SFTP successor storage backend identity is invalid"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpSuccessorRestaging).where(
            ExternalDocumentSourceSftpSuccessorRestaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpSuccessorRestaging.profile_id == profile_id,
            ExternalDocumentSourceSftpSuccessorRestaging.change_detection_id
            == change_detection_id,
        )
    )
    new_anchor = existing is None
    if existing is not None:
        _ensure_integrity(
            db,
            existing,
            verify_storage=existing.status == "completed",
        )
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP successor restaging"
            )
        if existing.status == "completed":
            return existing, "unchanged"
        row = existing
        change, checkpoint, staging, proof = _load_lineage(db, row)
    else:
        collision = db.scalar(
            select(ExternalDocumentSourceSftpSuccessorRestaging).where(
                ExternalDocumentSourceSftpSuccessorRestaging.organization_id
                == organization_id,
                ExternalDocumentSourceSftpSuccessorRestaging.profile_id
                == profile_id,
                ExternalDocumentSourceSftpSuccessorRestaging.request_key
                == normalized_key,
            )
        )
        if collision is not None:
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP successor restaging request_key"
            )

        change = db.scalar(
            select(ExternalDocumentSourceSftpChangeDetection)
            .where(
                ExternalDocumentSourceSftpChangeDetection.id
                == change_detection_id,
                ExternalDocumentSourceSftpChangeDetection.organization_id
                == organization_id,
                ExternalDocumentSourceSftpChangeDetection.profile_id == profile_id,
            )
            .with_for_update()
        )
        if change is None:
            raise ExternalDocumentSourceNotFoundError(
                "Phase 17.6-L SFTP change detection not found"
            )
        _ensure_change_detection_integrity(db, change)
        if (
            change.result_status != "changed"
            or change.observed_projection_hash is None
            or change.observed_byte_size is None
        ):
            raise ExternalDocumentSourceConflictError(
                "Only exact Phase 17.6-L changed-file observations are eligible for successor restaging"
            )
        if (
            change.observed_byte_size < 0
            or change.observed_byte_size > MAX_SFTP_SUCCESSOR_BYTES
        ):
            raise ExternalDocumentSourceConflictError(
                "Changed SFTP file exceeds the Phase 17.6-M byte bound"
            )

        checkpoint = db.scalar(
            select(ExternalDocumentSourceSftpCheckpoint).where(
                ExternalDocumentSourceSftpCheckpoint.id == change.checkpoint_id,
                ExternalDocumentSourceSftpCheckpoint.organization_id
                == organization_id,
                ExternalDocumentSourceSftpCheckpoint.profile_id == profile_id,
            )
        )
        if checkpoint is None:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-K checkpoint lineage is missing"
            )
        _ensure_checkpoint_integrity(db, checkpoint)

        staging = db.scalar(
            select(ExternalDocumentSourceSftpQuarantineStaging).where(
                ExternalDocumentSourceSftpQuarantineStaging.id
                == checkpoint.quarantine_staging_id,
                ExternalDocumentSourceSftpQuarantineStaging.organization_id
                == organization_id,
                ExternalDocumentSourceSftpQuarantineStaging.profile_id == profile_id,
            )
        )
        if staging is None:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-J quarantine lineage is missing"
            )
        _ensure_quarantine_staging_integrity(db, staging, verify_storage=False)
        if backend != staging.storage_backend_kind:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-M governed quarantine storage backend drifted from Phase 17.6-J"
            )

        proof = db.scalar(
            select(ExternalDocumentSourceSftpFileContentProof).where(
                ExternalDocumentSourceSftpFileContentProof.id
                == checkpoint.file_content_proof_id,
                ExternalDocumentSourceSftpFileContentProof.organization_id
                == organization_id,
                ExternalDocumentSourceSftpFileContentProof.profile_id == profile_id,
            )
        )
        if proof is None:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-I content-proof lineage is missing"
            )
        _ensure_file_content_proof_integrity(db, proof)

        requested_at = _aware(now or _utc_now())
        restaging_id = uuid4()
        successor_generation = checkpoint.checkpoint_generation + 1
        storage_key = _storage_key(
            restaging_id,
            organization_id,
            successor_generation,
        )
        storage_key_hash = hashlib.sha256(
            storage_key.encode("utf-8")
        ).hexdigest()
        scope_hash = _scope_hash(
            change,
            checkpoint,
            proof,
            storage_backend_kind=backend,
            storage_object_key_hash=storage_key_hash,
            successor_generation=successor_generation,
            request_key=normalized_key,
        )

        row = ExternalDocumentSourceSftpSuccessorRestaging(
            id=restaging_id,
            organization_id=organization_id,
            profile_id=profile_id,
            change_detection_id=change.id,
            checkpoint_id=checkpoint.id,
            quarantine_staging_id=staging.id,
            file_content_proof_id=proof.id,
            directory_listing_id=checkpoint.directory_listing_id,
            listing_entry_id=checkpoint.listing_entry_id,
            session_activation_id=staging.session_activation_id,
            credential_reference_binding_id=staging.credential_reference_binding_id,
            provider_kind="sftp",
            profile_hash=checkpoint.profile_hash,
            locator_hash=staging.locator_hash,
            authentication_kind=staging.authentication_kind,
            reference_backend=staging.reference_backend,
            destination_hostname=staging.destination_hostname,
            destination_port=staging.destination_port,
            pinned_host_key_fingerprint=staging.pinned_host_key_fingerprint,
            remote_root_path_hash=staging.remote_root_path_hash,
            checkpoint_state_hash=checkpoint.checkpoint_state_hash,
            checkpoint_completion_hash=checkpoint.completion_hash,
            predecessor_content_sha256=checkpoint.content_sha256,
            predecessor_content_byte_count=checkpoint.content_byte_count,
            change_scope_hash=change.scope_hash,
            change_request_hash=change.request_hash,
            change_completion_hash=change.completion_hash,
            observed_projection_hash=change.observed_projection_hash,
            observed_byte_size=change.observed_byte_size,
            listing_entry_hash=checkpoint.listing_entry_hash,
            read_operation_kind=_READ_OPERATION_KIND,
            read_policy_hash=_read_policy_hash(),
            read_adapter_kind=proof.read_adapter_kind,
            successor_generation=successor_generation,
            successor_content_sha256=None,
            successor_content_byte_count=None,
            successor_content_proof_hash=None,
            storage_backend_kind=backend,
            storage_purpose=SFTP_SUCCESSOR_STORAGE_PURPOSE,
            storage_object_key=storage_key,
            storage_object_key_hash=storage_key_hash,
            stored_etag=None,
            request_key=normalized_key,
            scope_hash=scope_hash,
            request_hash="0" * 64,
            status="requested",
            result_status=None,
            requested_by_id=requested_by_id,
            request_reason=normalized_reason,
            requested_at=requested_at,
            completed_at=None,
            completion_hash=None,
            **_base_safety(False),
        )
        row.request_hash = _request_hash(row)
        db.add(row)
        db.flush()
        _append_receipt(
            db,
            row=row,
            event_type="requested",
            actor_id=requested_by_id,
            occurred_at=requested_at,
            decision_hash=row.request_hash,
        )
        _ensure_integrity(db, row, verify_storage=False)

        # Persist recovery authority before any SFTP or object-store I/O.
        db.commit()
        db.refresh(row)

    if not new_anchor:
        try:
            metadata, digest, byte_count = _verify_successor_object(store, row)
        except ObjectStorageNotFound:
            metadata = None
        if metadata is not None:
            completed_at = max(_aware(row.requested_at), _utc_now())
            _complete_from_storage(
                db,
                row,
                metadata=metadata,
                digest=digest,
                byte_count=byte_count,
                completed_at=completed_at,
            )
            return row, "completed"

    listing, entry = _load_listing_and_entry(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        listing_id=proof.directory_listing_id,
        entry_id=proof.listing_entry_id,
        for_update=False,
    )
    binding, normalized = _active_binding_and_profile(db, listing)
    adapter = get_external_document_source_sftp_file_content_read_adapter()
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP content-read adapter is unavailable for Phase 17.6-M"
        )
    if (
        getattr(adapter, "adapter_kind", None) != proof.read_adapter_kind
        or proof.read_adapter_kind != staging.read_adapter_kind
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-M SFTP reread adapter drifted from prior verified lineage"
        )

    request = SftpFileContentReadRequest(
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

    payload: bytes | None = None
    try:
        transient_result = adapter.read_content(request)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "SFTP changed-file successor reread failed"
        ) from None

    try:
        payload, authentication_method, _latency_class = _validate_adapter_result(
            transient_result,
            expected_auth_kind=binding.authentication_kind,
            declared_byte_size=change.observed_byte_size,
        )
        digest = hashlib.sha256(payload).hexdigest()
        byte_count = len(payload)
        if (
            byte_count != change.observed_byte_size
            or byte_count > MAX_SFTP_SUCCESSOR_BYTES
        ):
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-M reread does not match the Phase 17.6-L observed byte size"
            )
        if digest == checkpoint.content_sha256:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-M reread produced the current checkpoint digest; no successor content version exists"
            )
        if authentication_method != proof.authentication_method:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-M authentication method drifted from Phase 17.6-I"
            )
        try:
            store.put_bytes_if_absent(
                payload,
                storage_key=row.storage_object_key,
                expected_sha256=digest,
            )
        except ObjectStoragePreconditionFailed:
            pass
        except ObjectStorageError:
            raise ExternalDocumentSourceConflictError(
                "Governed SFTP successor quarantine write failed"
            ) from None
    finally:
        if payload is not None:
            del payload
        try:
            del transient_result
        except UnboundLocalError:
            pass

    metadata, digest, byte_count = _verify_successor_object(store, row)
    completed_at = max(_aware(row.requested_at), _utc_now())
    _complete_from_storage(
        db,
        row,
        metadata=metadata,
        digest=digest,
        byte_count=byte_count,
        completed_at=completed_at,
    )
    return row, "completed"


def get_external_document_source_sftp_successor_restaging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    restaging_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSftpSuccessorRestaging).where(
            ExternalDocumentSourceSftpSuccessorRestaging.id == restaging_id,
            ExternalDocumentSourceSftpSuccessorRestaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpSuccessorRestaging.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP successor restaging execution not found"
        )
    _ensure_integrity(
        db,
        row,
        verify_storage=row.status == "completed",
    )
    return row


def list_external_document_source_sftp_successor_restaging_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    restaging_id: UUID,
):
    row = get_external_document_source_sftp_successor_restaging(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        restaging_id=restaging_id,
    )
    return _receipts(db, row)
