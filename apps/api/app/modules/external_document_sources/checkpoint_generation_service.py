from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.checkpoint_generation_models import (
    MAX_SUCCESSOR_CHECKPOINT_CONTENT_BYTES,
    PREDECESSOR_CHECKPOINT_GENERATION,
    SUCCESSOR_CHECKPOINT_GENERATION,
    SUCCESSOR_CHECKPOINT_KIND,
    ExternalDocumentSourceCheckpointGenerationExecution,
    ExternalDocumentSourceCheckpointGenerationReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sync_checkpoint_models import ExternalDocumentSourceSyncCheckpointExecution
from app.modules.external_document_sources.sync_checkpoint_service import _ensure_integrity as _ensure_sync_checkpoint_integrity
from app.modules.external_document_sources.versioned_restaging_models import (
    CANDIDATE_GENERATION,
    ExternalDocumentSourceVersionedRestagingExecution,
)
from app.modules.external_document_sources.versioned_restaging_service import _ensure_integrity as _ensure_versioned_restaging_integrity

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
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "upstream_remote_file_content_read_completed": True,
        "upstream_remote_content_staging_completed": True,
        "upstream_sync_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "upstream_versioned_restaging_completed": True,
        "provider_client_constructed": False,
        "exact_item_metadata_read_performed": False,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "durable_content_staged": False,
        "checkpoint_created": completed,
        "checkpoint_advanced": completed,
        "checkpoint_generation_advance_completed": completed,
        "sync_executed": False,
        "subscription_created": False,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "id_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_client_stored": False,
        "provider_response_body_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


def _successor_state_hash(
    predecessor: ExternalDocumentSourceSyncCheckpointExecution,
    candidate: ExternalDocumentSourceVersionedRestagingExecution,
) -> str:
    if predecessor.completion_hash is None or candidate.completion_hash is None or candidate.content_proof_hash is None:
        raise ExternalDocumentSourceConflictError("Checkpoint-generation upstream completion facts are incomplete")
    if candidate.content_sha256 is None or candidate.content_byte_count is None:
        raise ExternalDocumentSourceConflictError("Checkpoint-generation candidate content proof is incomplete")
    return _canonical_hash(
        {
            "organization_id": str(candidate.organization_id),
            "profile_id": str(candidate.profile_id),
            "provider_kind": candidate.provider_kind,
            "profile_hash": candidate.profile_hash,
            "predecessor_sync_checkpoint_execution_id": str(predecessor.id),
            "predecessor_checkpoint_generation": predecessor.checkpoint_generation,
            "predecessor_checkpoint_state_hash": predecessor.checkpoint_state_hash,
            "predecessor_checkpoint_completion_hash": predecessor.completion_hash,
            "versioned_restaging_execution_id": str(candidate.id),
            "change_detection_execution_id": str(candidate.change_detection_execution_id),
            "original_staging_execution_id": str(candidate.original_staging_execution_id),
            "listing_execution_id": str(candidate.listing_execution_id),
            "metadata_item_id": str(candidate.metadata_item_id),
            "candidate_scope_hash": candidate.scope_hash,
            "candidate_request_hash": candidate.request_hash,
            "candidate_content_proof_hash": candidate.content_proof_hash,
            "candidate_completion_hash": candidate.completion_hash,
            "candidate_generation": candidate.candidate_generation,
            "content_sha256": candidate.content_sha256,
            "content_byte_count": candidate.content_byte_count,
            "media_type_class": candidate.content_media_type_class,
            "version_token_hash": candidate.content_version_token_hash,
            "storage_backend_kind": candidate.storage_backend_kind,
            "storage_purpose": candidate.storage_purpose,
            "storage_object_key_hash": candidate.storage_object_key_hash,
            "successor_checkpoint_kind": SUCCESSOR_CHECKPOINT_KIND,
            "successor_checkpoint_generation": SUCCESSOR_CHECKPOINT_GENERATION,
        }
    )


def _scope_hash(
    predecessor: ExternalDocumentSourceSyncCheckpointExecution,
    candidate: ExternalDocumentSourceVersionedRestagingExecution,
    *,
    successor_checkpoint_state_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(candidate.organization_id),
            "profile_id": str(candidate.profile_id),
            "predecessor_sync_checkpoint_execution_id": str(predecessor.id),
            "predecessor_checkpoint_state_hash": predecessor.checkpoint_state_hash,
            "versioned_restaging_execution_id": str(candidate.id),
            "candidate_completion_hash": candidate.completion_hash,
            "successor_checkpoint_kind": SUCCESSOR_CHECKPOINT_KIND,
            "successor_checkpoint_generation": SUCCESSOR_CHECKPOINT_GENERATION,
            "successor_checkpoint_state_hash": successor_checkpoint_state_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceCheckpointGenerationExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "successor_checkpoint_state_hash": execution.successor_checkpoint_state_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceCheckpointGenerationExecution) -> str:
    if execution.completed_at is None or execution.result_status != "checkpoint_generation_advanced":
        raise ExternalDocumentSourceConflictError("Checkpoint-generation completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "predecessor_checkpoint_state_hash": execution.predecessor_checkpoint_state_hash,
            "candidate_completion_hash": execution.candidate_completion_hash,
            "successor_checkpoint_kind": execution.successor_checkpoint_kind,
            "successor_checkpoint_generation": execution.successor_checkpoint_generation,
            "successor_checkpoint_state_hash": execution.successor_checkpoint_state_hash,
            "result_status": execution.result_status,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceCheckpointGenerationReceipt) -> str:
    return _canonical_hash(
        {
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
        }
    )


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceCheckpointGenerationExecution,
) -> list[ExternalDocumentSourceCheckpointGenerationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceCheckpointGenerationReceipt)
            .where(
                ExternalDocumentSourceCheckpointGenerationReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceCheckpointGenerationReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceCheckpointGenerationReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceCheckpointGenerationExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceCheckpointGenerationReceipt(
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


def _get_candidate(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    candidate_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceVersionedRestagingExecution:
    stmt = select(ExternalDocumentSourceVersionedRestagingExecution).where(
        ExternalDocumentSourceVersionedRestagingExecution.id == candidate_id,
        ExternalDocumentSourceVersionedRestagingExecution.organization_id == organization_id,
        ExternalDocumentSourceVersionedRestagingExecution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    candidate = db.scalar(stmt)
    if candidate is None:
        raise ExternalDocumentSourceNotFoundError("Phase Q versioned-restaging execution not found")
    _ensure_versioned_restaging_integrity(db, candidate, verify_storage=False)
    return candidate


def _get_predecessor(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    predecessor_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceSyncCheckpointExecution:
    stmt = select(ExternalDocumentSourceSyncCheckpointExecution).where(
        ExternalDocumentSourceSyncCheckpointExecution.id == predecessor_id,
        ExternalDocumentSourceSyncCheckpointExecution.organization_id == organization_id,
        ExternalDocumentSourceSyncCheckpointExecution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    predecessor = db.scalar(stmt)
    if predecessor is None:
        raise ExternalDocumentSourceConflictError("Phase O predecessor synchronization checkpoint is missing")
    _ensure_sync_checkpoint_integrity(db, predecessor)
    return predecessor


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceCheckpointGenerationExecution:
    execution = db.scalar(
        select(ExternalDocumentSourceCheckpointGenerationExecution).where(
            ExternalDocumentSourceCheckpointGenerationExecution.id == execution_id,
            ExternalDocumentSourceCheckpointGenerationExecution.organization_id == organization_id,
            ExternalDocumentSourceCheckpointGenerationExecution.profile_id == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError("Checkpoint-generation execution not found")
    return execution


def _ensure_integrity(
    db: Session,
    execution: ExternalDocumentSourceCheckpointGenerationExecution,
) -> None:
    candidate = _get_candidate(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        candidate_id=execution.versioned_restaging_execution_id,
    )
    if (
        candidate.status != "completed"
        or candidate.result_status != "staged_candidate_verified"
        or candidate.candidate_generation != CANDIDATE_GENERATION
        or candidate.content_sha256 is None
        or candidate.content_byte_count is None
        or candidate.content_proof_hash is None
        or candidate.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Phase Q candidate is not eligible for checkpoint advancement")

    predecessor = _get_predecessor(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        predecessor_id=execution.predecessor_sync_checkpoint_execution_id,
    )
    if predecessor.id != candidate.sync_checkpoint_execution_id:
        raise ExternalDocumentSourceConflictError("Checkpoint-generation predecessor is not the Phase Q lineage checkpoint")

    if (
        execution.change_detection_execution_id != candidate.change_detection_execution_id
        or execution.original_staging_execution_id != candidate.original_staging_execution_id
        or execution.listing_execution_id != candidate.listing_execution_id
        or execution.metadata_item_id != candidate.metadata_item_id
        or execution.provider_kind != candidate.provider_kind
        or execution.profile_hash != candidate.profile_hash
        or execution.predecessor_checkpoint_generation != PREDECESSOR_CHECKPOINT_GENERATION
        or predecessor.checkpoint_generation != PREDECESSOR_CHECKPOINT_GENERATION
        or execution.predecessor_checkpoint_state_hash != predecessor.checkpoint_state_hash
        or execution.predecessor_checkpoint_completion_hash != predecessor.completion_hash
        or execution.candidate_scope_hash != candidate.scope_hash
        or execution.candidate_request_hash != candidate.request_hash
        or execution.candidate_content_proof_hash != candidate.content_proof_hash
        or execution.candidate_completion_hash != candidate.completion_hash
        or execution.candidate_generation != candidate.candidate_generation
        or execution.content_sha256 != candidate.content_sha256
        or execution.content_byte_count != candidate.content_byte_count
        or execution.media_type_class != candidate.content_media_type_class
        or execution.version_token_hash != candidate.content_version_token_hash
        or execution.storage_backend_kind != candidate.storage_backend_kind
        or execution.storage_purpose != candidate.storage_purpose
        or execution.storage_object_key_hash != candidate.storage_object_key_hash
        or execution.successor_checkpoint_kind != SUCCESSOR_CHECKPOINT_KIND
        or execution.successor_checkpoint_generation != SUCCESSOR_CHECKPOINT_GENERATION
    ):
        raise ExternalDocumentSourceConflictError("Checkpoint-generation lineage drifted")

    for value, label in (
        (execution.predecessor_checkpoint_state_hash, "predecessor checkpoint state hash"),
        (execution.predecessor_checkpoint_completion_hash, "predecessor checkpoint completion hash"),
        (execution.candidate_scope_hash, "candidate scope hash"),
        (execution.candidate_request_hash, "candidate request hash"),
        (execution.candidate_content_proof_hash, "candidate content proof hash"),
        (execution.candidate_completion_hash, "candidate completion hash"),
        (execution.content_sha256, "content SHA-256"),
        (execution.storage_object_key_hash, "storage object-key hash"),
        (execution.successor_checkpoint_state_hash, "successor checkpoint state hash"),
    ):
        if not _HEX_64.fullmatch(value):
            raise ExternalDocumentSourceConflictError(f"Checkpoint-generation {label} is invalid")
    if execution.version_token_hash is not None and not _HEX_64.fullmatch(execution.version_token_hash):
        raise ExternalDocumentSourceConflictError("Checkpoint-generation version-token hash is invalid")
    if not 0 <= execution.content_byte_count <= MAX_SUCCESSOR_CHECKPOINT_CONTENT_BYTES:
        raise ExternalDocumentSourceConflictError("Checkpoint-generation content byte count is invalid")

    expected_state_hash = _successor_state_hash(predecessor, candidate)
    expected_scope_hash = _scope_hash(
        predecessor,
        candidate,
        successor_checkpoint_state_hash=expected_state_hash,
        request_key=execution.request_key,
    )
    if (
        execution.successor_checkpoint_state_hash != expected_state_hash
        or execution.scope_hash != expected_scope_hash
        or execution.request_hash != _request_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError("Checkpoint-generation request integrity failed")

    expected_events = {
        "requested": ["requested"],
        "completed": ["requested", "completed"],
    }
    if execution.status not in expected_events:
        raise ExternalDocumentSourceConflictError("Checkpoint-generation status is invalid")
    rows = _receipts(db, execution)
    if [row.event_type for row in rows] != expected_events[execution.status]:
        raise ExternalDocumentSourceConflictError("Checkpoint-generation receipt lifecycle drifted")

    prior: str | None = None
    for index, receipt in enumerate(rows, start=1):
        completed = receipt.event_type == "completed"
        expected_time = execution.completed_at if completed else execution.requested_at
        expected_decision = execution.completion_hash if completed else execution.request_hash
        if (
            expected_time is None
            or expected_decision is None
            or receipt.sequence_number != index
            or receipt.status_after != receipt.event_type
            or receipt.actor_id != execution.requested_by_id
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != execution.request_reason
            or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != expected_decision
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError("Checkpoint-generation receipt integrity failed")
        for field, expected in _base_safety(completed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Checkpoint-generation receipt safety boundary drifted")
        prior = receipt.receipt_hash

    completed = execution.status == "completed"
    for field, expected in _base_safety(completed).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Checkpoint-generation safety boundary drifted")

    if not completed:
        if execution.result_status is not None or execution.completed_at is not None or execution.completion_hash is not None:
            raise ExternalDocumentSourceConflictError("Checkpoint-generation request lifecycle drifted")
        return
    if (
        execution.result_status != "checkpoint_generation_advanced"
        or execution.completed_at is None
        or _aware(execution.completed_at) < _aware(execution.requested_at)
        or execution.completion_hash != _completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError("Checkpoint-generation completion integrity failed")


def execute_external_document_source_checkpoint_generation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    versioned_restaging_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceCheckpointGenerationExecution).where(
            ExternalDocumentSourceCheckpointGenerationExecution.organization_id == organization_id,
            ExternalDocumentSourceCheckpointGenerationExecution.profile_id == profile_id,
            ExternalDocumentSourceCheckpointGenerationExecution.versioned_restaging_execution_id == versioned_restaging_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay or second consumption for checkpoint-generation advancement")
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceCheckpointGenerationExecution).where(
            ExternalDocumentSourceCheckpointGenerationExecution.organization_id == organization_id,
            ExternalDocumentSourceCheckpointGenerationExecution.profile_id == profile_id,
            ExternalDocumentSourceCheckpointGenerationExecution.request_key == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for checkpoint-generation request_key")

    candidate = _get_candidate(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        candidate_id=versioned_restaging_execution_id,
        for_update=True,
    )
    if (
        candidate.status != "completed"
        or candidate.result_status != "staged_candidate_verified"
        or candidate.candidate_generation != CANDIDATE_GENERATION
        or candidate.content_sha256 is None
        or candidate.content_byte_count is None
        or candidate.content_proof_hash is None
        or candidate.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Only a completed integrity-valid Phase Q generation-2 candidate is eligible")

    predecessor = _get_predecessor(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        predecessor_id=candidate.sync_checkpoint_execution_id,
        for_update=True,
    )
    if predecessor.checkpoint_generation != PREDECESSOR_CHECKPOINT_GENERATION:
        raise ExternalDocumentSourceConflictError("Phase R requires the exact Phase O generation-1 predecessor")

    competing = db.scalar(
        select(ExternalDocumentSourceCheckpointGenerationExecution).where(
            ExternalDocumentSourceCheckpointGenerationExecution.organization_id == organization_id,
            ExternalDocumentSourceCheckpointGenerationExecution.profile_id == profile_id,
            ExternalDocumentSourceCheckpointGenerationExecution.predecessor_sync_checkpoint_execution_id == predecessor.id,
        )
    )
    if competing is not None:
        _ensure_integrity(db, competing)
        raise ExternalDocumentSourceConflictError("The Phase O predecessor already has a generation-2 successor checkpoint")

    current = _aware(now or _utc_now())
    execution = ExternalDocumentSourceCheckpointGenerationExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        versioned_restaging_execution_id=candidate.id,
        predecessor_sync_checkpoint_execution_id=predecessor.id,
        change_detection_execution_id=candidate.change_detection_execution_id,
        original_staging_execution_id=candidate.original_staging_execution_id,
        listing_execution_id=candidate.listing_execution_id,
        metadata_item_id=candidate.metadata_item_id,
        provider_kind=candidate.provider_kind,
        profile_hash=candidate.profile_hash,
        predecessor_checkpoint_generation=PREDECESSOR_CHECKPOINT_GENERATION,
        predecessor_checkpoint_state_hash=predecessor.checkpoint_state_hash,
        predecessor_checkpoint_completion_hash=predecessor.completion_hash,
        candidate_scope_hash=candidate.scope_hash,
        candidate_request_hash=candidate.request_hash,
        candidate_content_proof_hash=candidate.content_proof_hash,
        candidate_completion_hash=candidate.completion_hash,
        candidate_generation=candidate.candidate_generation,
        content_sha256=candidate.content_sha256,
        content_byte_count=candidate.content_byte_count,
        media_type_class=candidate.content_media_type_class,
        version_token_hash=candidate.content_version_token_hash,
        storage_backend_kind=candidate.storage_backend_kind,
        storage_purpose=candidate.storage_purpose,
        storage_object_key_hash=candidate.storage_object_key_hash,
        successor_checkpoint_kind=SUCCESSOR_CHECKPOINT_KIND,
        successor_checkpoint_generation=SUCCESSOR_CHECKPOINT_GENERATION,
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
    db.add(execution)
    db.flush()

    execution.successor_checkpoint_state_hash = _successor_state_hash(predecessor, candidate)
    execution.scope_hash = _scope_hash(
        predecessor,
        candidate,
        successor_checkpoint_state_hash=execution.successor_checkpoint_state_hash,
        request_key=normalized_key,
    )
    execution.request_hash = _request_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        decision_hash=execution.request_hash,
    )

    execution.status = "completed"
    execution.result_status = "checkpoint_generation_advanced"
    execution.completed_at = current
    for field, value in _base_safety(True).items():
        setattr(execution, field, value)
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=current,
        decision_hash=execution.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_checkpoint_generation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = _get_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_checkpoint_generation_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_checkpoint_generation(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
