from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources import sftp_change_detection_service as base_change
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataRequest,
    _effective_remote_path,
    _observation_policy_hash,
    _relative_path_hash,
    _validate_adapter_result,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_models import (
    MAX_SFTP_GENERATION3_METADATA_BYTE_SIZE,
    SFTP_GENERATION3_BASELINE_GENERATION,
    ExternalDocumentSourceSftpGeneration3ChangeDetection,
    ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    SFTP_GENERATION3_CHECKPOINT_GENERATION,
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_service import (
    _ensure_integrity as _ensure_generation3_checkpoint_integrity,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    SFTP_GENERATION3_CANDIDATE_GENERATION,
    ExternalDocumentSourceSftpGeneration3Restaging,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    _active_binding_and_profile,
    _load_listing_and_entry,
)
from app.modules.external_document_sources.sftp_generation3_restaging_service import (
    _ensure_integrity as _ensure_generation3_restaging_integrity,
)
from app.modules.external_document_sources.sftp_successor_change_detection_models import (
    ExternalDocumentSourceSftpSuccessorChangeDetection,
)
from app.modules.external_document_sources.sftp_successor_change_detection_service import (
    _ensure_integrity as _ensure_successor_change_integrity,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_OBSERVATION_OPERATION_KIND = "sftp_generation3_exact_file_metadata_stat_v1"
_ALLOWED_AUTH_METHODS = frozenset({"password", "public_key"})
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_FALSE_FIELDS = (
    "credential_stored", "session_stored", "remote_content_transiently_observed",
    "remote_list_performed", "remote_read_performed", "remote_write_performed",
    "remote_rename_performed", "remote_delete_performed", "remote_mkdir_performed",
    "remote_chmod_performed", "remote_chown_performed", "remote_touch_performed",
    "command_executed", "storage_read_performed", "storage_write_performed",
    "storage_reconciliation_performed", "storage_delete_performed", "storage_copy_performed",
    "durable_content_staged", "checkpoint_created", "checkpoint_advanced",
    "subscription_created", "raw_response_stored", "remote_content_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed",
    "content_extracted", "evidence_admitted", "document_created",
    "processing_enqueued", "ai_executed", "claim_mutated",
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
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _safety(completed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "upstream_predecessor_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "upstream_successor_restaging_completed": True,
        "upstream_checkpoint_advancement_completed": True,
        "secret_resolution_performed": completed,
        "credential_stored": False,
        "session_stored": False,
        "provider_network_performed": completed,
        "ssh_transport_performed": completed,
        "host_key_verification_performed": completed,
        "host_key_verified": completed,
        "authentication_performed": completed,
        "authentication_succeeded": completed,
        "sftp_session_opened": completed,
        "sftp_session_closed": completed,
        "exact_item_metadata_read_performed": completed,
        "generation3_change_detection_completed": completed,
        "remote_stat_performed": completed,
        **{field: False for field in _FALSE_FIELDS},
    }


def _baseline_projection_hash(
    *,
    byte_size: int,
    modified_at: datetime | None,
    metadata_id_hash: str | None,
) -> str:
    return base_change._observed_projection_hash(
        entry_kind="file",
        byte_size=byte_size,
        modified_at=modified_at,
        metadata_id_hash=metadata_id_hash,
    )


def _load_lineage(
    db: Session,
    advancement: ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
):
    _ensure_generation3_checkpoint_integrity(db, advancement)
    if (
        advancement.status != "completed"
        or advancement.result_status != "checkpoint_advanced"
        or advancement.successor_checkpoint_generation
        != SFTP_GENERATION3_CHECKPOINT_GENERATION
        or advancement.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-Q generation-3 checkpoint is not eligible for observation"
        )

    candidate = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3Restaging).where(
            ExternalDocumentSourceSftpGeneration3Restaging.id
            == advancement.generation3_restaging_id,
            ExternalDocumentSourceSftpGeneration3Restaging.organization_id
            == advancement.organization_id,
            ExternalDocumentSourceSftpGeneration3Restaging.profile_id
            == advancement.profile_id,
        )
    )
    if candidate is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-P generation-3 restaging lineage is missing"
        )
    _ensure_generation3_restaging_integrity(db, candidate, verify_storage=False)

    observation = db.scalar(
        select(ExternalDocumentSourceSftpSuccessorChangeDetection).where(
            ExternalDocumentSourceSftpSuccessorChangeDetection.id
            == advancement.successor_change_detection_id,
            ExternalDocumentSourceSftpSuccessorChangeDetection.organization_id
            == advancement.organization_id,
            ExternalDocumentSourceSftpSuccessorChangeDetection.profile_id
            == advancement.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-O changed-observation lineage is missing"
        )
    _ensure_successor_change_integrity(db, observation)

    listing, entry = _load_listing_and_entry(
        db,
        organization_id=advancement.organization_id,
        profile_id=advancement.profile_id,
        listing_id=candidate.directory_listing_id,
        entry_id=candidate.listing_entry_id,
        for_update=False,
    )
    binding, normalized = _active_binding_and_profile(db, listing)

    baseline_projection_hash = _baseline_projection_hash(
        byte_size=advancement.content_byte_count,
        modified_at=candidate.observed_modified_at,
        metadata_id_hash=candidate.observed_metadata_id_hash,
    )
    if (
        candidate.id != advancement.generation3_restaging_id
        or candidate.checkpoint_advancement_id
        != advancement.predecessor_checkpoint_advancement_id
        or candidate.successor_change_detection_id != observation.id
        or candidate.candidate_generation != SFTP_GENERATION3_CANDIDATE_GENERATION
        or candidate.content_byte_count != advancement.content_byte_count
        or candidate.content_sha256 != advancement.content_sha256
        or candidate.content_proof_hash != advancement.candidate_content_proof_hash
        or candidate.completion_hash != advancement.candidate_completion_hash
        or observation.result_status != "changed"
        or candidate.successor_change_scope_hash != observation.scope_hash
        or candidate.successor_change_completion_hash != observation.completion_hash
        or candidate.observed_projection_hash != observation.observed_projection_hash
        or candidate.observed_byte_size != observation.observed_byte_size
        or candidate.observed_byte_size != advancement.content_byte_count
        or candidate.observed_metadata_id_hash != observation.observed_metadata_id_hash
        or (
            (candidate.observed_modified_at is None)
            != (observation.observed_modified_at is None)
        )
        or (
            candidate.observed_modified_at is not None
            and _aware(candidate.observed_modified_at)
            != _aware(observation.observed_modified_at)
        )
        or candidate.observed_projection_hash != baseline_projection_hash
        or listing.id != candidate.directory_listing_id
        or entry.id != candidate.listing_entry_id
        or binding.id != candidate.credential_reference_binding_id
        or entry.entry_kind != "file"
        or advancement.provider_kind != "sftp"
        or advancement.profile_hash != candidate.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 observation lineage drifted"
        )
    return (
        candidate,
        observation,
        listing,
        entry,
        binding,
        normalized,
        baseline_projection_hash,
    )

def _scope_hash(
    advancement: ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
    *,
    candidate: ExternalDocumentSourceSftpGeneration3Restaging,
    observation: ExternalDocumentSourceSftpSuccessorChangeDetection,
    baseline_projection_hash: str,
    entry,
    binding,
    adapter_kind: str,
    request_key: str,
) -> str:
    return _canonical_hash({
        "organization_id": str(advancement.organization_id),
        "profile_id": str(advancement.profile_id),
        "generation3_checkpoint_advancement_id": str(advancement.id),
        "successor_checkpoint_state_hash": advancement.successor_checkpoint_state_hash,
        "successor_checkpoint_completion_hash": advancement.completion_hash,
        "generation3_restaging_id": str(candidate.id),
        "candidate_content_proof_hash": candidate.content_proof_hash,
        "candidate_completion_hash": candidate.completion_hash,
        "predecessor_checkpoint_advancement_id": str(
            advancement.predecessor_checkpoint_advancement_id
        ),
        "successor_change_detection_id": str(observation.id),
        "successor_change_completion_hash": observation.completion_hash,
        "baseline_generation": SFTP_GENERATION3_BASELINE_GENERATION,
        "baseline_projection_hash": baseline_projection_hash,
        "listing_entry_id": str(entry.id),
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
        "storage_io_authorized": False,
        "checkpoint_advance_authorized": False,
    })

def _request_hash(row: ExternalDocumentSourceSftpGeneration3ChangeDetection) -> str:
    return _canonical_hash({
        "execution_id": str(row.id),
        "scope_hash": row.scope_hash,
        "requested_by_id": str(row.requested_by_id),
        "request_reason": row.request_reason,
        "requested_at": _iso(row.requested_at),
        **_safety(False),
    })


def _completion_hash(row: ExternalDocumentSourceSftpGeneration3ChangeDetection) -> str:
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


def _receipt_hash(receipt: ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt) -> str:
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


def _receipts(db: Session, row: ExternalDocumentSourceSftpGeneration3ChangeDetection):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt)
            .where(
                ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt.organization_id == row.organization_id,
                ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt.execution_id == row.id,
            )
            .order_by(ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipts(db: Session, row: ExternalDocumentSourceSftpGeneration3ChangeDetection) -> None:
    requested = ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt(
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
    completed = ExternalDocumentSourceSftpGeneration3ChangeDetectionReceipt(
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


def _classify(
    *,
    baseline_byte_size: int,
    baseline_modified_at: datetime | None,
    baseline_metadata_id_hash: str | None,
    observed: dict,
) -> dict:
    if observed["result_status"] == "missing":
        return observed
    dimensions: list[str] = []
    if observed["observed_byte_size"] != baseline_byte_size:
        dimensions.append("byte_size")
    if baseline_modified_at is not None and observed["observed_modified_at"] != _aware(baseline_modified_at):
        dimensions.append("modified_at")
    if baseline_metadata_id_hash is not None and observed["observed_metadata_id_hash"] != baseline_metadata_id_hash:
        dimensions.append("metadata_id")
    observed["result_status"] = "changed" if dimensions else "unchanged"
    observed["changed_dimensions"] = ",".join(dimensions) if dimensions else None
    return observed


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpGeneration3ChangeDetection,
) -> None:
    advancement = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement).where(
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.id
            == row.generation3_checkpoint_advancement_id,
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.profile_id
            == row.profile_id,
        )
    )
    if advancement is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 checkpoint lineage is missing"
        )
    (
        candidate,
        observation,
        listing,
        entry,
        binding,
        _normalized,
        baseline_projection_hash,
    ) = _load_lineage(db, advancement)

    if (
        row.generation3_restaging_id != candidate.id
        or row.predecessor_checkpoint_advancement_id
        != advancement.predecessor_checkpoint_advancement_id
        or row.successor_change_detection_id != observation.id
        or row.directory_listing_id != listing.id
        or row.listing_entry_id != entry.id
        or row.credential_reference_binding_id != binding.id
        or row.provider_kind != "sftp"
        or row.profile_hash != advancement.profile_hash
        or row.baseline_generation != SFTP_GENERATION3_BASELINE_GENERATION
        or row.successor_checkpoint_kind != advancement.successor_checkpoint_kind
        or row.successor_checkpoint_state_hash
        != advancement.successor_checkpoint_state_hash
        or row.successor_checkpoint_completion_hash != advancement.completion_hash
        or row.candidate_content_proof_hash != candidate.content_proof_hash
        or row.candidate_completion_hash != candidate.completion_hash
        or row.baseline_projection_hash != baseline_projection_hash
        or row.baseline_entry_hash != entry.entry_hash
        or row.baseline_relative_path_hash != _relative_path_hash(entry.relative_path)
        or row.baseline_entry_kind != "file"
        or row.baseline_byte_size != advancement.content_byte_count
        or (
            (row.baseline_modified_at is None)
            != (candidate.observed_modified_at is None)
        )
        or (
            row.baseline_modified_at is not None
            and _aware(row.baseline_modified_at)
            != _aware(candidate.observed_modified_at)
        )
        or row.baseline_metadata_id_hash != candidate.observed_metadata_id_hash
        or row.observation_operation_kind != _OBSERVATION_OPERATION_KIND
        or row.observation_policy_hash != _observation_policy_hash()
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 observation baseline lineage drifted"
        )

    for digest in (
        row.successor_checkpoint_state_hash,
        row.successor_checkpoint_completion_hash,
        row.candidate_content_proof_hash,
        row.candidate_completion_hash,
        row.baseline_projection_hash,
        row.baseline_entry_hash,
        row.baseline_relative_path_hash,
        row.scope_hash,
        row.request_hash,
        row.completion_hash,
    ):
        if not _HEX_64.fullmatch(digest):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 observation hash boundary drifted"
            )
    if (
        row.baseline_metadata_id_hash is not None
        and not _HEX_64.fullmatch(row.baseline_metadata_id_hash)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 observation baseline metadata hash is invalid"
        )
    if not 0 <= row.baseline_byte_size <= MAX_SFTP_GENERATION3_METADATA_BYTE_SIZE:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 observation baseline byte size is invalid"
        )

    expected_scope = _scope_hash(
        advancement,
        candidate=candidate,
        observation=observation,
        baseline_projection_hash=baseline_projection_hash,
        entry=entry,
        binding=binding,
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
            "SFTP generation-3 observation integrity failed"
        )

    if row.result_status == "missing":
        if any(value is not None for value in (
            row.observed_projection_hash,
            row.observed_entry_kind,
            row.observed_byte_size,
            row.observed_modified_at,
            row.observed_metadata_id_hash,
            row.changed_dimensions,
        )):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 missing observation contains unexpected metadata"
            )
    else:
        if (
            row.observed_projection_hash is None
            or row.observed_entry_kind != "file"
            or row.observed_byte_size is None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 observation metadata is incomplete"
            )
        expected_projection = base_change._observed_projection_hash(
            entry_kind="file",
            byte_size=row.observed_byte_size,
            modified_at=row.observed_modified_at,
            metadata_id_hash=row.observed_metadata_id_hash,
        )
        if row.observed_projection_hash != expected_projection:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 observed projection integrity failed"
            )
        classified = _classify(
            baseline_byte_size=row.baseline_byte_size,
            baseline_modified_at=row.baseline_modified_at,
            baseline_metadata_id_hash=row.baseline_metadata_id_hash,
            observed={
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
                "SFTP generation-3 observation classification integrity failed"
            )

    if (
        row.authentication_method not in _ALLOWED_AUTH_METHODS
        or row.latency_class not in _ALLOWED_LATENCY_CLASSES
        or _aware(row.completed_at) < _aware(row.requested_at)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 observation execution facts drifted"
        )
    for field, expected in _safety(True).items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 observation safety boundary drifted"
            )

    receipts = _receipts(db, row)
    if len(receipts) != 2:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 observation receipt chain is incomplete"
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
                "SFTP generation-3 observation receipt integrity failed"
            )
        for field, expected in _safety(completed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 observation receipt safety boundary drifted"
                )

def _check_replay(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    advancement_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
):
    existing = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3ChangeDetection).where(
            ExternalDocumentSourceSftpGeneration3ChangeDetection.organization_id
            == organization_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.profile_id
            == profile_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.request_key
            == request_key,
        )
    )
    if existing is None:
        return None
    _ensure_integrity(db, existing)
    if (
        existing.generation3_checkpoint_advancement_id != advancement_id
        or existing.requested_by_id != requested_by_id
        or existing.request_reason != request_reason
    ):
        raise ExternalDocumentSourceConflictError(
            "Conflicting replay for SFTP generation-3 exact-file observation"
        )
    return existing

def execute_external_document_source_sftp_generation3_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    generation3_checkpoint_advancement_id: UUID,
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

    existing = _check_replay(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        advancement_id=generation3_checkpoint_advancement_id,
        requested_by_id=requested_by_id,
        request_key=normalized_key,
        request_reason=normalized_reason,
    )
    if existing is not None:
        return existing, "unchanged"

    advancement = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement)
        .where(
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.id
            == generation3_checkpoint_advancement_id,
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.organization_id
            == organization_id,
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if advancement is None:
        raise ExternalDocumentSourceNotFoundError(
            "Phase 17.6-Q SFTP generation-3 checkpoint not found"
        )
    (
        candidate,
        observation,
        listing,
        entry,
        binding,
        normalized,
        baseline_projection_hash,
    ) = _load_lineage(db, advancement)

    existing = _check_replay(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        advancement_id=generation3_checkpoint_advancement_id,
        requested_by_id=requested_by_id,
        request_key=normalized_key,
        request_reason=normalized_reason,
    )
    if existing is not None:
        return existing, "unchanged"

    adapter = base_change._METADATA_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter is unavailable"
        )
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if (
        not isinstance(adapter_kind, str)
        or not base_change._SAFE_ADAPTER_KIND.fullmatch(adapter_kind)
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
            normalized["remote_root_path"], entry.relative_path
        ),
    )
    try:
        raw_result = adapter.stat_metadata(request)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 exact-file metadata observation failed"
        ) from None
    observed = _validate_adapter_result(
        raw_result,
        expected_auth_kind=binding.authentication_kind,
    )
    observed = _classify(
        baseline_byte_size=advancement.content_byte_count,
        baseline_modified_at=candidate.observed_modified_at,
        baseline_metadata_id_hash=candidate.observed_metadata_id_hash,
        observed=observed,
    )

    requested_at = _aware(now or _utc_now())
    completed_at = max(requested_at, _utc_now())
    scope_hash = _scope_hash(
        advancement,
        candidate=candidate,
        observation=observation,
        baseline_projection_hash=baseline_projection_hash,
        entry=entry,
        binding=binding,
        adapter_kind=adapter_kind,
        request_key=normalized_key,
    )
    row = ExternalDocumentSourceSftpGeneration3ChangeDetection(
        id=uuid4(),
        organization_id=organization_id,
        profile_id=profile_id,
        generation3_checkpoint_advancement_id=advancement.id,
        generation3_restaging_id=candidate.id,
        predecessor_checkpoint_advancement_id=advancement.predecessor_checkpoint_advancement_id,
        successor_change_detection_id=observation.id,
        directory_listing_id=listing.id,
        listing_entry_id=entry.id,
        credential_reference_binding_id=binding.id,
        provider_kind="sftp",
        profile_hash=advancement.profile_hash,
        baseline_generation=SFTP_GENERATION3_BASELINE_GENERATION,
        successor_checkpoint_kind=advancement.successor_checkpoint_kind,
        successor_checkpoint_state_hash=advancement.successor_checkpoint_state_hash,
        successor_checkpoint_completion_hash=advancement.completion_hash,
        candidate_content_proof_hash=candidate.content_proof_hash,
        candidate_completion_hash=candidate.completion_hash,
        baseline_projection_hash=baseline_projection_hash,
        baseline_entry_hash=entry.entry_hash,
        baseline_relative_path_hash=_relative_path_hash(entry.relative_path),
        baseline_entry_kind="file",
        baseline_byte_size=advancement.content_byte_count,
        baseline_modified_at=(
            _aware(candidate.observed_modified_at)
            if candidate.observed_modified_at is not None
            else None
        ),
        baseline_metadata_id_hash=candidate.observed_metadata_id_hash,
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

def get_external_document_source_sftp_generation3_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3ChangeDetection).where(
            ExternalDocumentSourceSftpGeneration3ChangeDetection.id == execution_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.organization_id == organization_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("SFTP generation-3 change-detection execution not found")
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_generation3_change_detection_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    row = get_external_document_source_sftp_generation3_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, row)
