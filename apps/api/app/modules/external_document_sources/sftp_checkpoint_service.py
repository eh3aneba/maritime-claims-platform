from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    MAX_SFTP_CHECKPOINT_CONTENT_BYTES,
    SFTP_CHECKPOINT_GENERATION,
    SFTP_CHECKPOINT_KIND,
    ExternalDocumentSourceSftpCheckpoint,
    ExternalDocumentSourceSftpCheckpointReceipt,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    _ensure_anchor_integrity as _ensure_quarantine_staging_integrity,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


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


def _base_safety(completed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "upstream_file_content_proof_completed": True,
        "upstream_quarantine_staging_completed": True,
        "secret_resolution_performed": False,
        "provider_network_performed": False,
        "ssh_transport_performed": False,
        "host_key_verification_performed": False,
        "authentication_performed": False,
        "sftp_session_opened": False,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_stat_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_rename_performed": False,
        "remote_delete_performed": False,
        "command_executed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "storage_copy_performed": False,
        "checkpoint_created": completed,
        "sync_executed": False,
        "credential_stored": False,
        "session_stored": False,
        "raw_response_stored": False,
        "remote_content_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "evidence_admitted": False,
        "document_created": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
    }


def _checkpoint_state_hash(
    staging: ExternalDocumentSourceSftpQuarantineStaging,
) -> str:
    if staging.completion_hash is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-J quarantine staging completion hash is missing"
        )
    return _canonical_hash(
        {
            "checkpoint_kind": SFTP_CHECKPOINT_KIND,
            "checkpoint_generation": SFTP_CHECKPOINT_GENERATION,
            "organization_id": str(staging.organization_id),
            "profile_id": str(staging.profile_id),
            "quarantine_staging_id": str(staging.id),
            "file_content_proof_id": str(staging.file_content_proof_id),
            "directory_listing_id": str(staging.directory_listing_id),
            "listing_entry_id": str(staging.listing_entry_id),
            "provider_kind": staging.provider_kind,
            "profile_hash": staging.profile_hash,
            "listing_entry_hash": staging.listing_entry_hash,
            "file_content_proof_result_hash": staging.upstream_result_hash,
            "staging_scope_hash": staging.scope_hash,
            "staging_request_hash": staging.request_hash,
            "staging_completion_hash": staging.completion_hash,
            "content_sha256": staging.expected_content_sha256,
            "content_byte_count": staging.expected_content_byte_count,
            "storage_backend_kind": staging.storage_backend_kind,
            "storage_purpose": staging.storage_purpose,
            "storage_object_key_hash": staging.storage_object_key_hash,
        }
    )


def _scope_hash(
    staging: ExternalDocumentSourceSftpQuarantineStaging,
    *,
    checkpoint_state_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(staging.organization_id),
            "profile_id": str(staging.profile_id),
            "quarantine_staging_id": str(staging.id),
            "staging_completion_hash": staging.completion_hash,
            "checkpoint_kind": SFTP_CHECKPOINT_KIND,
            "checkpoint_generation": SFTP_CHECKPOINT_GENERATION,
            "checkpoint_state_hash": checkpoint_state_hash,
            "request_key": request_key,
        }
    )


def _request_hash(row: ExternalDocumentSourceSftpCheckpoint) -> str:
    return _canonical_hash(
        {
            "checkpoint_id": str(row.id),
            "scope_hash": row.scope_hash,
            "checkpoint_state_hash": row.checkpoint_state_hash,
            "requested_by_id": str(row.requested_by_id),
            "request_reason": row.request_reason,
            "requested_at": _iso(row.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(row: ExternalDocumentSourceSftpCheckpoint) -> str:
    return _canonical_hash(
        {
            "checkpoint_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "checkpoint_kind": row.checkpoint_kind,
            "checkpoint_generation": row.checkpoint_generation,
            "checkpoint_state_hash": row.checkpoint_state_hash,
            "result_status": row.result_status,
            "completed_at": _iso(row.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpCheckpointReceipt,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "checkpoint_id": str(receipt.checkpoint_id),
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
    row: ExternalDocumentSourceSftpCheckpoint,
) -> list[ExternalDocumentSourceSftpCheckpointReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpCheckpointReceipt)
            .where(
                ExternalDocumentSourceSftpCheckpointReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpCheckpointReceipt.checkpoint_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpCheckpointReceipt.sequence_number.asc()
            )
        ).all()
    )


def _append_receipts(
    db: Session,
    row: ExternalDocumentSourceSftpCheckpoint,
) -> None:
    requested = ExternalDocumentSourceSftpCheckpointReceipt(
        organization_id=row.organization_id,
        checkpoint_id=row.id,
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
        **_base_safety(False),
    )
    requested.receipt_hash = _receipt_hash(requested)
    completed = ExternalDocumentSourceSftpCheckpointReceipt(
        organization_id=row.organization_id,
        checkpoint_id=row.id,
        sequence_number=2,
        event_type="completed",
        status_after="completed",
        actor_id=row.requested_by_id,
        occurred_at=row.completed_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=row.completion_hash,
        prior_receipt_hash=requested.receipt_hash,
        receipt_hash="0" * 64,
        **_base_safety(True),
    )
    completed.receipt_hash = _receipt_hash(completed)
    db.add_all([requested, completed])


def _get_staging(
    db: Session,
    row: ExternalDocumentSourceSftpCheckpoint,
) -> ExternalDocumentSourceSftpQuarantineStaging:
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
            "Phase 17.6-J quarantine staging lineage is missing"
        )
    return staging


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpCheckpoint,
) -> None:
    staging = _get_staging(db, row)
    _ensure_quarantine_staging_integrity(
        db,
        staging,
        verify_storage=False,
    )
    if (
        staging.status != "completed"
        or staging.result_status != "staged_verified"
        or staging.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-J quarantine staging is not complete"
        )

    if (
        row.file_content_proof_id != staging.file_content_proof_id
        or row.directory_listing_id != staging.directory_listing_id
        or row.listing_entry_id != staging.listing_entry_id
        or row.provider_kind != "sftp"
        or row.profile_hash != staging.profile_hash
        or row.listing_entry_hash != staging.listing_entry_hash
        or row.file_content_proof_result_hash != staging.upstream_result_hash
        or row.staging_scope_hash != staging.scope_hash
        or row.staging_request_hash != staging.request_hash
        or row.staging_completion_hash != staging.completion_hash
        or row.content_sha256 != staging.expected_content_sha256
        or row.content_byte_count != staging.expected_content_byte_count
        or row.storage_backend_kind != staging.storage_backend_kind
        or row.storage_purpose != staging.storage_purpose
        or row.storage_object_key_hash != staging.storage_object_key_hash
        or row.checkpoint_kind != SFTP_CHECKPOINT_KIND
        or row.checkpoint_generation != SFTP_CHECKPOINT_GENERATION
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint upstream snapshot lineage drifted"
        )

    for digest in (
        row.profile_hash,
        row.listing_entry_hash,
        row.file_content_proof_result_hash,
        row.staging_scope_hash,
        row.staging_request_hash,
        row.staging_completion_hash,
        row.content_sha256,
        row.storage_object_key_hash,
        row.checkpoint_state_hash,
        row.scope_hash,
        row.request_hash,
        row.completion_hash,
    ):
        if not _HEX_64.fullmatch(digest):
            raise ExternalDocumentSourceConflictError(
                "SFTP checkpoint hash boundary drifted"
            )
    if not 0 <= row.content_byte_count <= MAX_SFTP_CHECKPOINT_CONTENT_BYTES:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint content-size boundary drifted"
        )

    expected_state = _checkpoint_state_hash(staging)
    expected_scope = _scope_hash(
        staging,
        checkpoint_state_hash=expected_state,
        request_key=row.request_key,
    )
    if (
        row.checkpoint_state_hash != expected_state
        or row.scope_hash != expected_scope
        or row.request_hash != _request_hash(row)
        or row.completion_hash != _completion_hash(row)
        or row.status != "completed"
        or row.result_status != "checkpoint_recorded"
        or _aware(row.completed_at) < _aware(row.requested_at)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint integrity failed"
        )

    for field, expected in _base_safety(True).items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP checkpoint safety boundary drifted"
            )

    receipts = _receipts(db, row)
    if len(receipts) != 2:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint receipt chain is incomplete"
        )
    expected = (
        (1, "requested", "requested", row.requested_at, row.request_hash, None, False),
        (
            2,
            "completed",
            "completed",
            row.completed_at,
            row.completion_hash,
            receipts[0].receipt_hash,
            True,
        ),
    )
    for receipt, facts in zip(receipts, expected, strict=True):
        (
            sequence,
            event_type,
            status_after,
            occurred_at,
            decision_hash,
            prior_hash,
            completed,
        ) = facts
        if (
            receipt.sequence_number != sequence
            or receipt.event_type != event_type
            or receipt.status_after != status_after
            or receipt.actor_id != row.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != row.request_reason
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior_hash
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP checkpoint receipt integrity failed"
            )
        for field, expected_value in _base_safety(completed).items():
            if bool(getattr(receipt, field)) != expected_value:
                raise ExternalDocumentSourceConflictError(
                    "SFTP checkpoint receipt safety boundary drifted"
                )


def create_external_document_source_sftp_checkpoint(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    quarantine_staging_id: UUID,
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
        select(ExternalDocumentSourceSftpCheckpoint).where(
            ExternalDocumentSourceSftpCheckpoint.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCheckpoint.profile_id
            == profile_id,
            ExternalDocumentSourceSftpCheckpoint.quarantine_staging_id
            == quarantine_staging_id,
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
                "Conflicting replay for SFTP checkpoint"
            )
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceSftpCheckpoint).where(
            ExternalDocumentSourceSftpCheckpoint.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCheckpoint.profile_id
            == profile_id,
            ExternalDocumentSourceSftpCheckpoint.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "Conflicting replay for SFTP checkpoint request_key"
        )

    staging = db.scalar(
        select(ExternalDocumentSourceSftpQuarantineStaging)
        .where(
            ExternalDocumentSourceSftpQuarantineStaging.id
            == quarantine_staging_id,
            ExternalDocumentSourceSftpQuarantineStaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpQuarantineStaging.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if staging is None:
        raise ExternalDocumentSourceNotFoundError(
            "Phase 17.6-J SFTP quarantine staging not found"
        )
    _ensure_quarantine_staging_integrity(
        db,
        staging,
        verify_storage=False,
    )
    if (
        staging.status != "completed"
        or staging.result_status != "staged_verified"
        or staging.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-J SFTP quarantine staging is not eligible for checkpoint custody"
        )

    second = db.scalar(
        select(ExternalDocumentSourceSftpCheckpoint).where(
            ExternalDocumentSourceSftpCheckpoint.quarantine_staging_id
            == staging.id
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
                "Conflicting replay for SFTP checkpoint"
            )
        return second, "unchanged"

    requested_at = _aware(now or _utc_now())
    completed_at = max(requested_at, _utc_now())
    checkpoint_state_hash = _checkpoint_state_hash(staging)
    scope_hash = _scope_hash(
        staging,
        checkpoint_state_hash=checkpoint_state_hash,
        request_key=normalized_key,
    )

    row = ExternalDocumentSourceSftpCheckpoint(
        id=uuid4(),
        organization_id=organization_id,
        profile_id=profile_id,
        quarantine_staging_id=staging.id,
        file_content_proof_id=staging.file_content_proof_id,
        directory_listing_id=staging.directory_listing_id,
        listing_entry_id=staging.listing_entry_id,
        provider_kind="sftp",
        profile_hash=staging.profile_hash,
        listing_entry_hash=staging.listing_entry_hash,
        file_content_proof_result_hash=staging.upstream_result_hash,
        staging_scope_hash=staging.scope_hash,
        staging_request_hash=staging.request_hash,
        staging_completion_hash=staging.completion_hash,
        content_sha256=staging.expected_content_sha256,
        content_byte_count=staging.expected_content_byte_count,
        storage_backend_kind=staging.storage_backend_kind,
        storage_purpose=staging.storage_purpose,
        storage_object_key_hash=staging.storage_object_key_hash,
        checkpoint_kind=SFTP_CHECKPOINT_KIND,
        checkpoint_generation=SFTP_CHECKPOINT_GENERATION,
        checkpoint_state_hash=checkpoint_state_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="completed",
        result_status="checkpoint_recorded",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        completed_at=completed_at,
        completion_hash="0" * 64,
        **_base_safety(True),
    )
    row.request_hash = _request_hash(row)
    row.completion_hash = _completion_hash(row)
    db.add(row)
    db.flush()
    _append_receipts(db, row)
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_checkpoint(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    checkpoint_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSftpCheckpoint).where(
            ExternalDocumentSourceSftpCheckpoint.id == checkpoint_id,
            ExternalDocumentSourceSftpCheckpoint.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCheckpoint.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP checkpoint not found"
        )
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_checkpoint_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    checkpoint_id: UUID,
):
    row = get_external_document_source_sftp_checkpoint(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        checkpoint_id=checkpoint_id,
    )
    return _receipts(db, row)
