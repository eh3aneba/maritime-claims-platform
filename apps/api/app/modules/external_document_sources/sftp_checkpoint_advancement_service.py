from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_checkpoint_advancement_models import (
    MAX_SFTP_SUCCESSOR_CHECKPOINT_BYTES,
    SFTP_PREDECESSOR_CHECKPOINT_GENERATION,
    SFTP_SUCCESSOR_CHECKPOINT_GENERATION,
    SFTP_SUCCESSOR_CHECKPOINT_KIND,
    ExternalDocumentSourceSftpCheckpointAdvancement,
    ExternalDocumentSourceSftpCheckpointAdvancementReceipt,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_checkpoint_service import (
    _ensure_integrity as _ensure_sftp_checkpoint_integrity,
)
from app.modules.external_document_sources.sftp_successor_restaging_models import (
    ExternalDocumentSourceSftpSuccessorRestaging,
)
from app.modules.external_document_sources.sftp_successor_restaging_service import (
    _ensure_integrity as _ensure_sftp_successor_restaging_integrity,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


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
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _base_safety(completed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "upstream_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "upstream_successor_restaging_completed": True,
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
        "remote_mkdir_performed": False,
        "remote_chmod_performed": False,
        "remote_chown_performed": False,
        "remote_touch_performed": False,
        "command_executed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_reconciliation_performed": False,
        "storage_delete_performed": False,
        "storage_copy_performed": False,
        "durable_content_staged": False,
        "checkpoint_created": completed,
        "checkpoint_advanced": completed,
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


def _successor_state_hash(
    predecessor: ExternalDocumentSourceSftpCheckpoint,
    candidate: ExternalDocumentSourceSftpSuccessorRestaging,
) -> str:
    if (
        predecessor.completion_hash is None
        or candidate.completion_hash is None
        or candidate.successor_content_proof_hash is None
        or candidate.successor_content_sha256 is None
        or candidate.successor_content_byte_count is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement upstream completion facts are incomplete"
        )
    return _canonical_hash(
        {
            "organization_id": str(candidate.organization_id),
            "profile_id": str(candidate.profile_id),
            "provider_kind": candidate.provider_kind,
            "profile_hash": candidate.profile_hash,
            "predecessor_checkpoint_id": str(predecessor.id),
            "predecessor_checkpoint_generation": predecessor.checkpoint_generation,
            "predecessor_checkpoint_state_hash": predecessor.checkpoint_state_hash,
            "predecessor_checkpoint_completion_hash": predecessor.completion_hash,
            "successor_restaging_id": str(candidate.id),
            "change_detection_id": str(candidate.change_detection_id),
            "quarantine_staging_id": str(candidate.quarantine_staging_id),
            "file_content_proof_id": str(candidate.file_content_proof_id),
            "directory_listing_id": str(candidate.directory_listing_id),
            "listing_entry_id": str(candidate.listing_entry_id),
            "candidate_scope_hash": candidate.scope_hash,
            "candidate_request_hash": candidate.request_hash,
            "candidate_content_proof_hash": candidate.successor_content_proof_hash,
            "candidate_completion_hash": candidate.completion_hash,
            "candidate_generation": candidate.successor_generation,
            "content_sha256": candidate.successor_content_sha256,
            "content_byte_count": candidate.successor_content_byte_count,
            "storage_backend_kind": candidate.storage_backend_kind,
            "storage_purpose": candidate.storage_purpose,
            "storage_object_key_hash": candidate.storage_object_key_hash,
            "successor_checkpoint_kind": SFTP_SUCCESSOR_CHECKPOINT_KIND,
            "successor_checkpoint_generation": SFTP_SUCCESSOR_CHECKPOINT_GENERATION,
        }
    )


def _scope_hash(
    predecessor: ExternalDocumentSourceSftpCheckpoint,
    candidate: ExternalDocumentSourceSftpSuccessorRestaging,
    *,
    successor_checkpoint_state_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(candidate.organization_id),
            "profile_id": str(candidate.profile_id),
            "predecessor_checkpoint_id": str(predecessor.id),
            "predecessor_checkpoint_state_hash": predecessor.checkpoint_state_hash,
            "successor_restaging_id": str(candidate.id),
            "candidate_completion_hash": candidate.completion_hash,
            "successor_checkpoint_kind": SFTP_SUCCESSOR_CHECKPOINT_KIND,
            "successor_checkpoint_generation": SFTP_SUCCESSOR_CHECKPOINT_GENERATION,
            "successor_checkpoint_state_hash": successor_checkpoint_state_hash,
            "request_key": request_key,
        }
    )


def _request_hash(row: ExternalDocumentSourceSftpCheckpointAdvancement) -> str:
    return _canonical_hash(
        {
            "advancement_id": str(row.id),
            "scope_hash": row.scope_hash,
            "successor_checkpoint_state_hash": row.successor_checkpoint_state_hash,
            "requested_by_id": str(row.requested_by_id),
            "request_reason": row.request_reason,
            "requested_at": _iso(row.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(row: ExternalDocumentSourceSftpCheckpointAdvancement) -> str:
    if row.completed_at is None or row.result_status != "checkpoint_advanced":
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement completion facts are incomplete"
        )
    return _canonical_hash(
        {
            "advancement_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "predecessor_checkpoint_state_hash": row.predecessor_checkpoint_state_hash,
            "candidate_completion_hash": row.candidate_completion_hash,
            "successor_checkpoint_kind": row.successor_checkpoint_kind,
            "successor_checkpoint_generation": row.successor_checkpoint_generation,
            "successor_checkpoint_state_hash": row.successor_checkpoint_state_hash,
            "result_status": row.result_status,
            "completed_at": _iso(row.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceSftpCheckpointAdvancementReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "advancement_id": str(receipt.advancement_id),
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
    row: ExternalDocumentSourceSftpCheckpointAdvancement,
) -> list[ExternalDocumentSourceSftpCheckpointAdvancementReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpCheckpointAdvancementReceipt)
            .where(
                ExternalDocumentSourceSftpCheckpointAdvancementReceipt.organization_id == row.organization_id,
                ExternalDocumentSourceSftpCheckpointAdvancementReceipt.advancement_id == row.id,
            )
            .order_by(ExternalDocumentSourceSftpCheckpointAdvancementReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceSftpCheckpointAdvancement,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    receipts = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpCheckpointAdvancementReceipt(
        organization_id=row.organization_id,
        advancement_id=row.id,
        sequence_number=len(receipts) + 1,
        event_type=event_type,
        status_after=row.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=receipts[-1].receipt_hash if receipts else None,
        **_base_safety(event_type == "completed"),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _get_candidate(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    restaging_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceSftpSuccessorRestaging:
    stmt = select(ExternalDocumentSourceSftpSuccessorRestaging).where(
        ExternalDocumentSourceSftpSuccessorRestaging.id == restaging_id,
        ExternalDocumentSourceSftpSuccessorRestaging.organization_id == organization_id,
        ExternalDocumentSourceSftpSuccessorRestaging.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    candidate = db.scalar(stmt)
    if candidate is None:
        raise ExternalDocumentSourceNotFoundError(
            "Phase 17.6-M SFTP successor restaging not found"
        )
    _ensure_sftp_successor_restaging_integrity(db, candidate, verify_storage=False)
    return candidate


def _get_predecessor(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    checkpoint_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceSftpCheckpoint:
    stmt = select(ExternalDocumentSourceSftpCheckpoint).where(
        ExternalDocumentSourceSftpCheckpoint.id == checkpoint_id,
        ExternalDocumentSourceSftpCheckpoint.organization_id == organization_id,
        ExternalDocumentSourceSftpCheckpoint.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    predecessor = db.scalar(stmt)
    if predecessor is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-K predecessor checkpoint is missing"
        )
    _ensure_sftp_checkpoint_integrity(db, predecessor)
    return predecessor


def _get_advancement(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    advancement_id: UUID,
) -> ExternalDocumentSourceSftpCheckpointAdvancement:
    row = db.scalar(
        select(ExternalDocumentSourceSftpCheckpointAdvancement).where(
            ExternalDocumentSourceSftpCheckpointAdvancement.id == advancement_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.organization_id == organization_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP checkpoint advancement not found"
        )
    return row


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpCheckpointAdvancement,
) -> None:
    candidate = _get_candidate(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        restaging_id=row.successor_restaging_id,
    )
    if (
        candidate.status != "completed"
        or candidate.result_status != "successor_staged_verified"
        or candidate.successor_content_sha256 is None
        or candidate.successor_content_byte_count is None
        or candidate.successor_content_proof_hash is None
        or candidate.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-M successor candidate is not eligible for checkpoint advancement"
        )

    predecessor = _get_predecessor(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        checkpoint_id=row.predecessor_checkpoint_id,
    )
    if candidate.checkpoint_id != predecessor.id:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint advancement predecessor is not the candidate lineage checkpoint"
        )

    if (
        row.change_detection_id != candidate.change_detection_id
        or row.quarantine_staging_id != candidate.quarantine_staging_id
        or row.file_content_proof_id != candidate.file_content_proof_id
        or row.directory_listing_id != candidate.directory_listing_id
        or row.listing_entry_id != candidate.listing_entry_id
        or row.provider_kind != "sftp"
        or row.profile_hash != candidate.profile_hash
        or row.predecessor_checkpoint_generation != predecessor.checkpoint_generation
        or row.predecessor_checkpoint_generation != SFTP_PREDECESSOR_CHECKPOINT_GENERATION
        or row.predecessor_checkpoint_state_hash != predecessor.checkpoint_state_hash
        or row.predecessor_checkpoint_completion_hash != predecessor.completion_hash
        or row.candidate_scope_hash != candidate.scope_hash
        or row.candidate_request_hash != candidate.request_hash
        or row.candidate_content_proof_hash != candidate.successor_content_proof_hash
        or row.candidate_completion_hash != candidate.completion_hash
        or row.candidate_generation != candidate.successor_generation
        or row.content_sha256 != candidate.successor_content_sha256
        or row.content_byte_count != candidate.successor_content_byte_count
        or row.storage_backend_kind != candidate.storage_backend_kind
        or row.storage_purpose != candidate.storage_purpose
        or row.storage_object_key_hash != candidate.storage_object_key_hash
        or row.successor_checkpoint_kind != SFTP_SUCCESSOR_CHECKPOINT_KIND
        or row.successor_checkpoint_generation != SFTP_SUCCESSOR_CHECKPOINT_GENERATION
        or row.candidate_generation != predecessor.checkpoint_generation + 1
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement lineage drifted"
        )

    for value, label in (
        (row.predecessor_checkpoint_state_hash, "predecessor checkpoint state hash"),
        (row.predecessor_checkpoint_completion_hash, "predecessor checkpoint completion hash"),
        (row.candidate_scope_hash, "candidate scope hash"),
        (row.candidate_request_hash, "candidate request hash"),
        (row.candidate_content_proof_hash, "candidate content proof hash"),
        (row.candidate_completion_hash, "candidate completion hash"),
        (row.content_sha256, "content SHA-256"),
        (row.storage_object_key_hash, "storage object-key hash"),
        (row.successor_checkpoint_state_hash, "successor checkpoint state hash"),
    ):
        if not _HEX_64.fullmatch(value):
            raise ExternalDocumentSourceConflictError(
                f"SFTP checkpoint-advancement {label} is invalid"
            )
    if not 0 <= row.content_byte_count <= MAX_SFTP_SUCCESSOR_CHECKPOINT_BYTES:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement content byte count is invalid"
        )

    expected_state = _successor_state_hash(predecessor, candidate)
    expected_scope = _scope_hash(
        predecessor,
        candidate,
        successor_checkpoint_state_hash=expected_state,
        request_key=row.request_key,
    )
    if (
        row.successor_checkpoint_state_hash != expected_state
        or row.scope_hash != expected_scope
        or row.request_hash != _request_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement request integrity failed"
        )

    expected_events = {
        "requested": ["requested"],
        "completed": ["requested", "completed"],
    }
    if row.status not in expected_events:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement status is invalid"
        )
    receipts = _receipts(db, row)
    if [receipt.event_type for receipt in receipts] != expected_events[row.status]:
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement receipt lifecycle drifted"
        )

    prior: str | None = None
    for index, receipt in enumerate(receipts, start=1):
        completed = receipt.event_type == "completed"
        expected_time = row.completed_at if completed else row.requested_at
        expected_decision = row.completion_hash if completed else row.request_hash
        if (
            expected_time is None
            or expected_decision is None
            or receipt.sequence_number != index
            or receipt.status_after != receipt.event_type
            or receipt.actor_id != row.requested_by_id
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != row.request_reason
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != expected_decision
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP checkpoint-advancement receipt integrity failed"
            )
        for field, expected in _base_safety(completed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP checkpoint-advancement receipt safety boundary drifted"
                )
        prior = receipt.receipt_hash

    completed = row.status == "completed"
    for field, expected in _base_safety(completed).items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP checkpoint-advancement safety boundary drifted"
            )

    if not completed:
        if row.result_status is not None or row.completed_at is not None or row.completion_hash is not None:
            raise ExternalDocumentSourceConflictError(
                "SFTP checkpoint-advancement request lifecycle drifted"
            )
        return

    if (
        row.result_status != "checkpoint_advanced"
        or row.completed_at is None
        or _aware(row.completed_at) < _aware(row.requested_at)
        or row.completion_hash != _completion_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP checkpoint-advancement completion integrity failed"
        )


def execute_external_document_source_sftp_checkpoint_advancement(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    successor_restaging_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceSftpCheckpointAdvancement).where(
            ExternalDocumentSourceSftpCheckpointAdvancement.organization_id == organization_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.profile_id == profile_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.successor_restaging_id == successor_restaging_id,
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
                "Conflicting replay or second SFTP checkpoint advancement"
            )
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceSftpCheckpointAdvancement).where(
            ExternalDocumentSourceSftpCheckpointAdvancement.organization_id == organization_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.profile_id == profile_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.request_key == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "Conflicting replay for SFTP checkpoint-advancement request_key"
        )

    candidate = _get_candidate(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        restaging_id=successor_restaging_id,
        for_update=True,
    )
    if (
        candidate.status != "completed"
        or candidate.result_status != "successor_staged_verified"
        or candidate.successor_content_sha256 is None
        or candidate.successor_content_byte_count is None
        or candidate.successor_content_proof_hash is None
        or candidate.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Only a completed integrity-valid Phase 17.6-M successor candidate is eligible"
        )

    predecessor = _get_predecessor(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        checkpoint_id=candidate.checkpoint_id,
        for_update=True,
    )
    if (
        predecessor.checkpoint_generation != SFTP_PREDECESSOR_CHECKPOINT_GENERATION
        or candidate.successor_generation != predecessor.checkpoint_generation + 1
        or candidate.successor_generation != SFTP_SUCCESSOR_CHECKPOINT_GENERATION
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-N requires the exact generation-1 predecessor and generation-2 successor candidate"
        )

    competing = db.scalar(
        select(ExternalDocumentSourceSftpCheckpointAdvancement).where(
            ExternalDocumentSourceSftpCheckpointAdvancement.organization_id == organization_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.profile_id == profile_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.predecessor_checkpoint_id == predecessor.id,
        )
    )
    if competing is not None:
        _ensure_integrity(db, competing)
        raise ExternalDocumentSourceConflictError(
            "The Phase 17.6-K predecessor already has a successor checkpoint"
        )

    current = _aware(now or _utc_now())
    row = ExternalDocumentSourceSftpCheckpointAdvancement(
        organization_id=organization_id,
        profile_id=profile_id,
        successor_restaging_id=candidate.id,
        predecessor_checkpoint_id=predecessor.id,
        change_detection_id=candidate.change_detection_id,
        quarantine_staging_id=candidate.quarantine_staging_id,
        file_content_proof_id=candidate.file_content_proof_id,
        directory_listing_id=candidate.directory_listing_id,
        listing_entry_id=candidate.listing_entry_id,
        provider_kind="sftp",
        profile_hash=candidate.profile_hash,
        predecessor_checkpoint_generation=predecessor.checkpoint_generation,
        predecessor_checkpoint_state_hash=predecessor.checkpoint_state_hash,
        predecessor_checkpoint_completion_hash=predecessor.completion_hash,
        candidate_scope_hash=candidate.scope_hash,
        candidate_request_hash=candidate.request_hash,
        candidate_content_proof_hash=candidate.successor_content_proof_hash,
        candidate_completion_hash=candidate.completion_hash,
        candidate_generation=candidate.successor_generation,
        content_sha256=candidate.successor_content_sha256,
        content_byte_count=candidate.successor_content_byte_count,
        storage_backend_kind=candidate.storage_backend_kind,
        storage_purpose=candidate.storage_purpose,
        storage_object_key_hash=candidate.storage_object_key_hash,
        successor_checkpoint_kind=SFTP_SUCCESSOR_CHECKPOINT_KIND,
        successor_checkpoint_generation=SFTP_SUCCESSOR_CHECKPOINT_GENERATION,
        successor_checkpoint_state_hash="0" * 64,
        request_key=normalized_key,
        scope_hash="0" * 64,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        **_base_safety(False),
    )
    db.add(row)
    db.flush()

    row.successor_checkpoint_state_hash = _successor_state_hash(predecessor, candidate)
    row.scope_hash = _scope_hash(
        predecessor,
        candidate,
        successor_checkpoint_state_hash=row.successor_checkpoint_state_hash,
        request_key=normalized_key,
    )
    row.request_hash = _request_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        decision_hash=row.request_hash,
    )

    row.status = "completed"
    row.result_status = "checkpoint_advanced"
    row.completed_at = current
    for field, value in _base_safety(True).items():
        setattr(row, field, value)
    row.completion_hash = _completion_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=current,
        decision_hash=row.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_checkpoint_advancement(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    advancement_id: UUID,
):
    row = _get_advancement(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        advancement_id=advancement_id,
    )
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_checkpoint_advancement_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    advancement_id: UUID,
):
    row = get_external_document_source_sftp_checkpoint_advancement(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        advancement_id=advancement_id,
    )
    return _receipts(db, row)
