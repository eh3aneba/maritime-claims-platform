from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.remote_content_staging_models import (
    ExternalDocumentSourceRemoteContentStagingExecution,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    _ensure_anchor_integrity as _ensure_remote_content_staging_integrity,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sync_checkpoint_models import (
    CHECKPOINT_GENERATION,
    CHECKPOINT_KIND,
    MAX_CHECKPOINT_CONTENT_BYTES,
    ExternalDocumentSourceSyncCheckpointExecution,
    ExternalDocumentSourceSyncCheckpointReceipt,
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
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        "provider_client_constructed": False,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "durable_content_staged": False,
        "remote_content_stored": False,
        "checkpoint_created": completed,
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


def _checkpoint_state_hash(staging: ExternalDocumentSourceRemoteContentStagingExecution) -> str:
    if staging.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase N staging completion hash is missing")
    return _canonical_hash(
        {
            "checkpoint_kind": CHECKPOINT_KIND,
            "checkpoint_generation": CHECKPOINT_GENERATION,
            "organization_id": str(staging.organization_id),
            "profile_id": str(staging.profile_id),
            "remote_content_staging_execution_id": str(staging.id),
            "remote_content_read_execution_id": str(staging.remote_content_read_execution_id),
            "listing_execution_id": str(staging.listing_execution_id),
            "metadata_item_id": str(staging.metadata_item_id),
            "provider_kind": staging.provider_kind,
            "profile_hash": staging.profile_hash,
            "metadata_item_hash": staging.metadata_item_hash,
            "staging_scope_hash": staging.scope_hash,
            "staging_request_hash": staging.request_hash,
            "staging_completion_hash": staging.completion_hash,
            "content_sha256": staging.expected_content_sha256,
            "content_byte_count": staging.expected_content_byte_count,
            "media_type_class": staging.expected_media_type_class,
            "version_token_hash": staging.expected_version_token_hash,
            "storage_backend_kind": staging.storage_backend_kind,
            "storage_purpose": staging.storage_purpose,
            "storage_object_key_hash": staging.storage_object_key_hash,
        }
    )


def _scope_hash(
    staging: ExternalDocumentSourceRemoteContentStagingExecution,
    *,
    checkpoint_state_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(staging.organization_id),
            "profile_id": str(staging.profile_id),
            "remote_content_staging_execution_id": str(staging.id),
            "staging_completion_hash": staging.completion_hash,
            "checkpoint_kind": CHECKPOINT_KIND,
            "checkpoint_generation": CHECKPOINT_GENERATION,
            "checkpoint_state_hash": checkpoint_state_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceSyncCheckpointExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "checkpoint_state_hash": execution.checkpoint_state_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceSyncCheckpointExecution) -> str:
    if execution.completed_at is None or execution.result_status != "checkpoint_recorded":
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "checkpoint_kind": execution.checkpoint_kind,
            "checkpoint_generation": execution.checkpoint_generation,
            "checkpoint_state_hash": execution.checkpoint_state_hash,
            "result_status": execution.result_status,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceSyncCheckpointReceipt) -> str:
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
    execution: ExternalDocumentSourceSyncCheckpointExecution,
) -> list[ExternalDocumentSourceSyncCheckpointReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceSyncCheckpointReceipt)
            .where(
                ExternalDocumentSourceSyncCheckpointReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceSyncCheckpointReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceSyncCheckpointReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceSyncCheckpointExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceSyncCheckpointReceipt(
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


def _get_staging(
    db: Session,
    execution: ExternalDocumentSourceSyncCheckpointExecution,
) -> ExternalDocumentSourceRemoteContentStagingExecution:
    staging = db.scalar(
        select(ExternalDocumentSourceRemoteContentStagingExecution).where(
            ExternalDocumentSourceRemoteContentStagingExecution.id == execution.remote_content_staging_execution_id,
            ExternalDocumentSourceRemoteContentStagingExecution.organization_id == execution.organization_id,
            ExternalDocumentSourceRemoteContentStagingExecution.profile_id == execution.profile_id,
        )
    )
    if staging is None:
        raise ExternalDocumentSourceConflictError("Phase N remote content staging lineage is missing")
    return staging


def _ensure_integrity(
    db: Session,
    execution: ExternalDocumentSourceSyncCheckpointExecution,
) -> None:
    staging = _get_staging(db, execution)
    # Phase O is intentionally control-plane only: verify the complete persisted
    # Phase N lineage without issuing a fresh object-store HEAD/GET.
    _ensure_remote_content_staging_integrity(db, staging, verify_storage=False)
    if staging.status != "completed" or staging.result_status != "staged_verified" or staging.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase N remote content staging is not complete")

    if (
        execution.remote_content_read_execution_id != staging.remote_content_read_execution_id
        or execution.listing_execution_id != staging.listing_execution_id
        or execution.metadata_item_id != staging.metadata_item_id
        or execution.provider_kind != staging.provider_kind
        or execution.profile_hash != staging.profile_hash
        or execution.metadata_item_hash != staging.metadata_item_hash
        or execution.staging_scope_hash != staging.scope_hash
        or execution.staging_request_hash != staging.request_hash
        or execution.staging_completion_hash != staging.completion_hash
        or execution.content_sha256 != staging.expected_content_sha256
        or execution.content_byte_count != staging.expected_content_byte_count
        or execution.media_type_class != staging.expected_media_type_class
        or execution.version_token_hash != staging.expected_version_token_hash
        or execution.storage_backend_kind != staging.storage_backend_kind
        or execution.storage_purpose != staging.storage_purpose
        or execution.storage_object_key_hash != staging.storage_object_key_hash
        or execution.checkpoint_kind != CHECKPOINT_KIND
        or execution.checkpoint_generation != CHECKPOINT_GENERATION
    ):
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint upstream snapshot lineage drifted")

    if (
        not _HEX_64.fullmatch(execution.content_sha256)
        or not 0 <= execution.content_byte_count <= MAX_CHECKPOINT_CONTENT_BYTES
        or not _HEX_64.fullmatch(execution.storage_object_key_hash)
    ):
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint snapshot proof drifted")
    if execution.version_token_hash is not None and not _HEX_64.fullmatch(execution.version_token_hash):
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint version proof drifted")

    expected_state_hash = _checkpoint_state_hash(staging)
    expected_scope_hash = _scope_hash(
        staging,
        checkpoint_state_hash=expected_state_hash,
        request_key=execution.request_key,
    )
    if (
        execution.checkpoint_state_hash != expected_state_hash
        or execution.scope_hash != expected_scope_hash
        or execution.request_hash != _request_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint request integrity failed")

    if (
        execution.status != "completed"
        or execution.result_status != "checkpoint_recorded"
        or execution.completed_at is None
        or execution.completion_hash != _completion_hash(execution)
        or _aware(execution.completed_at) < _aware(execution.requested_at)
    ):
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint completion integrity failed")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Synchronization checkpoint safety boundary drifted")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Synchronization checkpoint receipt lifecycle is incomplete")
    expected_rows = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior: str | None = None
    for receipt, facts in zip(rows, expected_rows, strict=True):
        sequence, event_type, occurred_at, decision_hash, completed = facts
        if (
            receipt.sequence_number != sequence
            or receipt.event_type != event_type
            or receipt.status_after != event_type
            or receipt.actor_id != execution.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != execution.request_reason
            or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
        ):
            raise ExternalDocumentSourceConflictError("Synchronization checkpoint receipt facts drifted")
        for field, expected in _base_safety(completed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Synchronization checkpoint receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Synchronization checkpoint receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_sync_checkpoint(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    remote_content_staging_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceSyncCheckpointExecution).where(
            ExternalDocumentSourceSyncCheckpointExecution.organization_id == organization_id,
            ExternalDocumentSourceSyncCheckpointExecution.profile_id == profile_id,
            ExternalDocumentSourceSyncCheckpointExecution.remote_content_staging_execution_id == remote_content_staging_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for synchronization checkpoint execution")
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceSyncCheckpointExecution).where(
            ExternalDocumentSourceSyncCheckpointExecution.organization_id == organization_id,
            ExternalDocumentSourceSyncCheckpointExecution.profile_id == profile_id,
            ExternalDocumentSourceSyncCheckpointExecution.request_key == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for synchronization checkpoint request_key")

    staging = db.scalar(
        select(ExternalDocumentSourceRemoteContentStagingExecution)
        .where(
            ExternalDocumentSourceRemoteContentStagingExecution.id == remote_content_staging_execution_id,
            ExternalDocumentSourceRemoteContentStagingExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteContentStagingExecution.profile_id == profile_id,
        )
        .with_for_update()
    )
    if staging is None:
        raise ExternalDocumentSourceNotFoundError("Phase N remote content staging execution not found")
    _ensure_remote_content_staging_integrity(db, staging, verify_storage=False)
    if staging.status != "completed" or staging.result_status != "staged_verified" or staging.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase N remote content staging is not eligible for checkpoint custody")

    second = db.scalar(
        select(ExternalDocumentSourceSyncCheckpointExecution).where(
            ExternalDocumentSourceSyncCheckpointExecution.remote_content_staging_execution_id == staging.id
        )
    )
    if second is not None:
        _ensure_integrity(db, second)
        if (
            second.request_key != normalized_key
            or second.request_reason != normalized_reason
            or second.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for synchronization checkpoint execution")
        return second, "unchanged"

    current = _aware(now or _utc_now())
    state_hash = _checkpoint_state_hash(staging)
    scope_hash = _scope_hash(staging, checkpoint_state_hash=state_hash, request_key=normalized_key)
    execution = ExternalDocumentSourceSyncCheckpointExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        remote_content_staging_execution_id=staging.id,
        remote_content_read_execution_id=staging.remote_content_read_execution_id,
        listing_execution_id=staging.listing_execution_id,
        metadata_item_id=staging.metadata_item_id,
        provider_kind=staging.provider_kind,
        profile_hash=staging.profile_hash,
        metadata_item_hash=staging.metadata_item_hash,
        staging_scope_hash=staging.scope_hash,
        staging_request_hash=staging.request_hash,
        staging_completion_hash=staging.completion_hash,
        content_sha256=staging.expected_content_sha256,
        content_byte_count=staging.expected_content_byte_count,
        media_type_class=staging.expected_media_type_class,
        version_token_hash=staging.expected_version_token_hash,
        storage_backend_kind=staging.storage_backend_kind,
        storage_purpose=staging.storage_purpose,
        storage_object_key_hash=staging.storage_object_key_hash,
        checkpoint_kind=CHECKPOINT_KIND,
        checkpoint_generation=CHECKPOINT_GENERATION,
        checkpoint_state_hash=state_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        **_base_safety(False),
    )
    db.add(execution)
    db.flush()
    execution.request_hash = _request_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        decision_hash=execution.request_hash,
    )

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.result_status = "checkpoint_recorded"
    execution.completed_at = completed_at
    execution.checkpoint_created = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=completed_at,
        decision_hash=execution.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_sync_checkpoint(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = db.scalar(
        select(ExternalDocumentSourceSyncCheckpointExecution).where(
            ExternalDocumentSourceSyncCheckpointExecution.id == execution_id,
            ExternalDocumentSourceSyncCheckpointExecution.organization_id == organization_id,
            ExternalDocumentSourceSyncCheckpointExecution.profile_id == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError("Synchronization checkpoint execution not found")
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_sync_checkpoint_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_sync_checkpoint(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
