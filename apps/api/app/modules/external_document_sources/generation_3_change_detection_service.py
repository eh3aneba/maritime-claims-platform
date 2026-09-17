from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.change_detection_service import (
    _OBSERVATION_ADAPTERS,
    _changed_dimensions,
    _endpoint_policy_hash,
    _normalize_identifier,
    _policy,
    _projection_hash,
    _validate_result,
)
from app.modules.external_document_sources.checkpoint_generation_3_models import (
    SUCCESSOR_CHECKPOINT_GENERATION,
    SUCCESSOR_CHECKPOINT_KIND,
    ExternalDocumentSourceCheckpointGeneration3Execution,
)
from app.modules.external_document_sources.checkpoint_generation_3_service import (
    _ensure_integrity as _ensure_checkpoint_generation_3_integrity,
)
from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.generation_3_change_detection_models import (
    GENERATION_3_BASELINE_GENERATION,
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    ExternalDocumentSourceGeneration3ChangeDetectionReceipt,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
)
from app.modules.external_document_sources.remote_metadata_listing_service import _active_binding, _health_execution
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
)
from app.modules.external_document_sources.successor_change_detection_service import (
    _ensure_integrity as _ensure_successor_change_detection_integrity,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    SUCCESSOR_CANDIDATE_GENERATION,
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
)
from app.modules.external_document_sources.successor_versioned_restaging_service import (
    _ensure_integrity as _ensure_successor_versioned_restaging_integrity,
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
        "upstream_checkpoint_generation_advance_completed": True,
        "upstream_successor_change_detection_completed": True,
        "upstream_successor_versioned_restaging_completed": True,
        "upstream_checkpoint_generation_3_advance_completed": True,
        "provider_client_constructed": completed,
        "exact_item_metadata_read_performed": completed,
        "generation_3_successor_change_detection_completed": completed,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "durable_content_staged": False,
        "checkpoint_created": False,
        "checkpoint_advanced": False,
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


def _baseline_facts(observation: ExternalDocumentSourceSuccessorChangeDetectionExecution) -> dict:
    if (
        observation.status != "completed"
        or observation.result_status != "changed"
        or observation.observed_projection_hash is None
        or observation.observed_provider_item_id_hash is None
        or observation.observed_item_kind != "file"
        or observation.observed_display_name_hash is None
        or observation.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Phase S changed observation is not a complete generation-3 baseline")
    facts = {
        "provider_item_id_hash": observation.observed_provider_item_id_hash,
        "item_kind": observation.observed_item_kind,
        "display_name_hash": observation.observed_display_name_hash,
        "parent_item_id_hash": observation.observed_parent_item_id_hash,
        "mime_type_class": observation.observed_mime_type_class,
        "byte_size": observation.observed_byte_size,
        "modified_at": observation.observed_modified_at,
        "version_token_hash": observation.observed_version_token_hash,
    }
    if _projection_hash(facts) != observation.observed_projection_hash:
        raise ExternalDocumentSourceConflictError("Phase S observed generation-3 baseline projection drifted")
    return facts


def _persisted_baseline_facts(execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution) -> dict:
    return {
        "provider_item_id_hash": execution.baseline_provider_item_id_hash,
        "item_kind": execution.baseline_item_kind,
        "display_name_hash": execution.baseline_display_name_hash,
        "parent_item_id_hash": execution.baseline_parent_item_id_hash,
        "mime_type_class": execution.baseline_mime_type_class,
        "byte_size": execution.baseline_byte_size,
        "modified_at": execution.baseline_modified_at,
        "version_token_hash": execution.baseline_version_token_hash,
    }


def _persisted_observed_facts(execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution) -> dict:
    return {
        "provider_item_id_hash": execution.observed_provider_item_id_hash,
        "item_kind": execution.observed_item_kind,
        "display_name_hash": execution.observed_display_name_hash,
        "parent_item_id_hash": execution.observed_parent_item_id_hash,
        "mime_type_class": execution.observed_mime_type_class,
        "byte_size": execution.observed_byte_size,
        "modified_at": execution.observed_modified_at,
        "version_token_hash": execution.observed_version_token_hash,
    }


def _scope_hash(
    checkpoint: ExternalDocumentSourceCheckpointGeneration3Execution,
    observation: ExternalDocumentSourceSuccessorChangeDetectionExecution,
    *,
    baseline_projection_hash: str,
    observation_operation_kind: str,
    observation_adapter_kind: str,
    endpoint_policy_hash: str,
    request_key: str,
) -> str:
    if checkpoint.completion_hash is None or observation.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Generation-3 observation lineage completion hash is missing")
    return _canonical_hash(
        {
            "organization_id": str(checkpoint.organization_id),
            "profile_id": str(checkpoint.profile_id),
            "checkpoint_generation_3_execution_id": str(checkpoint.id),
            "successor_checkpoint_kind": checkpoint.successor_checkpoint_kind,
            "successor_checkpoint_generation": checkpoint.successor_checkpoint_generation,
            "successor_checkpoint_state_hash": checkpoint.successor_checkpoint_state_hash,
            "successor_checkpoint_completion_hash": checkpoint.completion_hash,
            "successor_versioned_restaging_execution_id": str(checkpoint.successor_versioned_restaging_execution_id),
            "candidate_content_proof_hash": checkpoint.candidate_content_proof_hash,
            "candidate_completion_hash": checkpoint.candidate_completion_hash,
            "successor_change_detection_execution_id": str(observation.id),
            "successor_change_scope_hash": observation.scope_hash,
            "successor_change_request_hash": observation.request_hash,
            "successor_change_completion_hash": observation.completion_hash,
            "baseline_projection_hash": baseline_projection_hash,
            "observation_operation_kind": observation_operation_kind,
            "observation_adapter_kind": observation_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "checkpoint_generation_3_execution_id": str(execution.checkpoint_generation_3_execution_id),
            "baseline_projection_hash": execution.baseline_projection_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution) -> str:
    if execution.completed_at is None or execution.result_status not in {"unchanged", "changed", "missing"}:
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "result_status": execution.result_status,
            "observed_projection_hash": execution.observed_projection_hash,
            "observed_provider_item_id_hash": execution.observed_provider_item_id_hash,
            "observed_item_kind": execution.observed_item_kind,
            "observed_display_name_hash": execution.observed_display_name_hash,
            "observed_parent_item_id_hash": execution.observed_parent_item_id_hash,
            "observed_mime_type_class": execution.observed_mime_type_class,
            "observed_byte_size": execution.observed_byte_size,
            "observed_modified_at": _iso(execution.observed_modified_at),
            "observed_version_token_hash": execution.observed_version_token_hash,
            "changed_dimensions": execution.changed_dimensions,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceGeneration3ChangeDetectionReceipt) -> str:
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


def _receipts(db: Session, execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution):
    return list(
        db.scalars(
            select(ExternalDocumentSourceGeneration3ChangeDetectionReceipt)
            .where(
                ExternalDocumentSourceGeneration3ChangeDetectionReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceGeneration3ChangeDetectionReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceGeneration3ChangeDetectionReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceGeneration3ChangeDetectionReceipt(
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


def _checkpoint_generation_3(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceCheckpointGeneration3Execution:
    stmt = select(ExternalDocumentSourceCheckpointGeneration3Execution).where(
        ExternalDocumentSourceCheckpointGeneration3Execution.id == execution_id,
        ExternalDocumentSourceCheckpointGeneration3Execution.organization_id == organization_id,
        ExternalDocumentSourceCheckpointGeneration3Execution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Phase U checkpoint-generation-3 execution not found")
    _ensure_checkpoint_generation_3_integrity(db, row)
    if (
        row.status != "completed"
        or row.result_status != "checkpoint_generation_3_advanced"
        or row.successor_checkpoint_generation != SUCCESSOR_CHECKPOINT_GENERATION
        or row.successor_checkpoint_kind != SUCCESSOR_CHECKPOINT_KIND
        or row.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Phase U generation-3 checkpoint is not eligible for observation")
    return row


def _lineage(
    db: Session,
    checkpoint: ExternalDocumentSourceCheckpointGeneration3Execution,
):
    candidate = db.scalar(
        select(ExternalDocumentSourceSuccessorVersionedRestagingExecution).where(
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.id == checkpoint.successor_versioned_restaging_execution_id,
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.organization_id == checkpoint.organization_id,
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.profile_id == checkpoint.profile_id,
        )
    )
    if candidate is None:
        raise ExternalDocumentSourceConflictError("Phase T generation-3 candidate lineage is missing")
    _ensure_successor_versioned_restaging_integrity(db, candidate, verify_storage=False)
    if (
        candidate.status != "completed"
        or candidate.result_status != "staged_candidate_verified"
        or candidate.candidate_generation != SUCCESSOR_CANDIDATE_GENERATION
        or candidate.content_proof_hash is None
        or candidate.completion_hash is None
        or candidate.content_sha256 is None
        or candidate.content_byte_count is None
    ):
        raise ExternalDocumentSourceConflictError("Phase T generation-3 candidate is incomplete")

    observation = db.scalar(
        select(ExternalDocumentSourceSuccessorChangeDetectionExecution).where(
            ExternalDocumentSourceSuccessorChangeDetectionExecution.id == checkpoint.successor_change_detection_execution_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.organization_id == checkpoint.organization_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.profile_id == checkpoint.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError("Phase S changed-observation lineage is missing")
    _ensure_successor_change_detection_integrity(db, observation)
    baseline = _baseline_facts(observation)
    baseline_hash = _projection_hash(baseline)

    if (
        candidate.id != checkpoint.successor_versioned_restaging_execution_id
        or candidate.successor_change_detection_execution_id != observation.id
        or checkpoint.successor_change_detection_execution_id != observation.id
        or checkpoint.predecessor_checkpoint_generation_execution_id != candidate.checkpoint_generation_execution_id
        or checkpoint.versioned_restaging_execution_id != candidate.versioned_restaging_execution_id
        or checkpoint.predecessor_sync_checkpoint_execution_id != candidate.predecessor_sync_checkpoint_execution_id
        or checkpoint.change_detection_execution_id != candidate.change_detection_execution_id
        or checkpoint.listing_execution_id != candidate.listing_execution_id
        or checkpoint.metadata_item_id != candidate.metadata_item_id
        or checkpoint.provider_kind != candidate.provider_kind
        or checkpoint.profile_hash != candidate.profile_hash
        or checkpoint.successor_change_scope_hash != observation.scope_hash
        or checkpoint.successor_change_request_hash != observation.request_hash
        or checkpoint.successor_change_completion_hash != observation.completion_hash
        or checkpoint.observed_projection_hash != baseline_hash
        or candidate.successor_change_scope_hash != observation.scope_hash
        or candidate.successor_change_request_hash != observation.request_hash
        or candidate.successor_change_completion_hash != observation.completion_hash
        or candidate.observed_projection_hash != baseline_hash
        or candidate.observed_provider_item_id_hash != baseline["provider_item_id_hash"]
        or candidate.observed_version_token_hash != baseline["version_token_hash"]
        or candidate.observed_byte_size != baseline["byte_size"]
        or candidate.observed_mime_type_class != baseline["mime_type_class"]
        or checkpoint.candidate_content_proof_hash != candidate.content_proof_hash
        or checkpoint.candidate_completion_hash != candidate.completion_hash
        or checkpoint.candidate_generation != candidate.candidate_generation
        or checkpoint.content_sha256 != candidate.content_sha256
        or checkpoint.content_byte_count != candidate.content_byte_count
        or checkpoint.version_token_hash != candidate.content_version_token_hash
        or checkpoint.media_type_class != candidate.content_media_type_class
        or checkpoint.storage_backend_kind != candidate.storage_backend_kind
        or checkpoint.storage_purpose != candidate.storage_purpose
        or checkpoint.storage_object_key_hash != candidate.storage_object_key_hash
    ):
        raise ExternalDocumentSourceConflictError("Generation-3 observation U/T/S lineage drifted")

    if baseline["byte_size"] is not None and checkpoint.content_byte_count != baseline["byte_size"]:
        raise ExternalDocumentSourceConflictError("Generation-3 checkpoint byte count does not reconcile to the Phase S baseline")
    if baseline["version_token_hash"] is not None and checkpoint.version_token_hash != baseline["version_token_hash"]:
        raise ExternalDocumentSourceConflictError("Generation-3 checkpoint version does not reconcile to the Phase S baseline")
    if baseline["mime_type_class"] is not None and checkpoint.media_type_class != baseline["mime_type_class"]:
        raise ExternalDocumentSourceConflictError("Generation-3 checkpoint media type does not reconcile to the Phase S baseline")

    listing = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.id == checkpoint.listing_execution_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == checkpoint.organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == checkpoint.profile_id,
        )
    )
    if listing is None:
        raise ExternalDocumentSourceConflictError("Phase L metadata-listing lineage is missing")
    item = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingItem).where(
            ExternalDocumentSourceRemoteMetadataListingItem.id == checkpoint.metadata_item_id,
            ExternalDocumentSourceRemoteMetadataListingItem.organization_id == checkpoint.organization_id,
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == listing.id,
        )
    )
    if item is None or item.item_kind != "file":
        raise ExternalDocumentSourceConflictError("Generation-3 exact metadata-item lineage is missing or not a file")
    if hashlib.sha256(item.provider_item_id.encode("utf-8")).hexdigest() != baseline["provider_item_id_hash"]:
        raise ExternalDocumentSourceConflictError("Generation-3 exact provider-item identity drifted")

    profile = _get_profile(db, organization_id=checkpoint.organization_id, profile_id=checkpoint.profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != checkpoint.profile_hash:
        raise ExternalDocumentSourceConflictError("Generation-3 observation source profile is not active")

    health_execution = _health_execution(db, listing)
    binding = _active_binding(db, health_execution)
    locator = CredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    policy = _policy(profile.provider_kind, profile.normalized_config, item.provider_item_id)
    return candidate, observation, listing, item, profile, locator, policy, baseline, baseline_hash


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceGeneration3ChangeDetectionExecution) -> None:
    checkpoint = _checkpoint_generation_3(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        execution_id=execution.checkpoint_generation_3_execution_id,
    )
    candidate, observation, _listing, _item, _profile, _locator, policy, baseline, baseline_hash = _lineage(db, checkpoint)
    expected_policy_hash = _endpoint_policy_hash(policy)

    if (
        execution.successor_versioned_restaging_execution_id != candidate.id
        or execution.successor_change_detection_execution_id != observation.id
        or execution.predecessor_checkpoint_generation_execution_id != checkpoint.predecessor_checkpoint_generation_execution_id
        or execution.versioned_restaging_execution_id != checkpoint.versioned_restaging_execution_id
        or execution.predecessor_sync_checkpoint_execution_id != checkpoint.predecessor_sync_checkpoint_execution_id
        or execution.change_detection_execution_id != checkpoint.change_detection_execution_id
        or execution.listing_execution_id != checkpoint.listing_execution_id
        or execution.metadata_item_id != checkpoint.metadata_item_id
        or execution.provider_kind != checkpoint.provider_kind
        or execution.profile_hash != checkpoint.profile_hash
        or execution.baseline_generation != GENERATION_3_BASELINE_GENERATION
        or execution.successor_checkpoint_kind != checkpoint.successor_checkpoint_kind
        or execution.successor_checkpoint_state_hash != checkpoint.successor_checkpoint_state_hash
        or execution.successor_checkpoint_completion_hash != checkpoint.completion_hash
        or execution.candidate_content_proof_hash != candidate.content_proof_hash
        or execution.candidate_completion_hash != candidate.completion_hash
        or execution.successor_change_scope_hash != observation.scope_hash
        or execution.successor_change_request_hash != observation.request_hash
        or execution.successor_change_completion_hash != observation.completion_hash
        or execution.baseline_projection_hash != baseline_hash
        or execution.baseline_provider_item_id_hash != baseline["provider_item_id_hash"]
        or execution.baseline_item_kind != baseline["item_kind"]
        or execution.baseline_display_name_hash != baseline["display_name_hash"]
        or execution.baseline_parent_item_id_hash != baseline["parent_item_id_hash"]
        or execution.baseline_version_token_hash != baseline["version_token_hash"]
        or execution.baseline_byte_size != baseline["byte_size"]
        or _iso(execution.baseline_modified_at) != _iso(baseline["modified_at"])
        or execution.baseline_mime_type_class != baseline["mime_type_class"]
        or execution.observation_operation_kind != policy.observation_operation_kind
        or execution.endpoint_policy_hash != expected_policy_hash
    ):
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection baseline lineage drifted")

    adapter_kind = _normalize_identifier(execution.observation_adapter_kind, field="Generation-3 change-detection adapter kind")
    expected_scope = _scope_hash(
        checkpoint,
        observation,
        baseline_projection_hash=baseline_hash,
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=expected_policy_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection request integrity failed")

    if execution.status != "completed" or execution.result_status not in {"unchanged", "changed", "missing"}:
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection lifecycle is incomplete")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection timestamps drifted")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Generation-3 change-detection safety boundary drifted")

    if execution.result_status == "missing":
        observed_fields = (
            execution.observed_projection_hash,
            execution.observed_provider_item_id_hash,
            execution.observed_item_kind,
            execution.observed_display_name_hash,
            execution.observed_parent_item_id_hash,
            execution.observed_version_token_hash,
            execution.observed_byte_size,
            execution.observed_modified_at,
            execution.observed_mime_type_class,
        )
        if any(value is not None for value in observed_fields) or execution.changed_dimensions != "missing":
            raise ExternalDocumentSourceConflictError("Generation-3 missing-item observation facts drifted")
    else:
        observed = _persisted_observed_facts(execution)
        if (
            execution.observed_provider_item_id_hash is None
            or execution.observed_item_kind != "file"
            or execution.observed_display_name_hash is None
            or execution.observed_provider_item_id_hash != execution.baseline_provider_item_id_hash
        ):
            raise ExternalDocumentSourceConflictError("Generation-3 observed exact-item identity drifted")
        if execution.observed_projection_hash != _projection_hash(observed):
            raise ExternalDocumentSourceConflictError("Generation-3 observed metadata projection integrity failed")
        expected_dimensions = _changed_dimensions(_persisted_baseline_facts(execution), observed)
        expected_result = "unchanged" if not expected_dimensions else "changed"
        if execution.result_status != expected_result or execution.changed_dimensions != ",".join(expected_dimensions):
            raise ExternalDocumentSourceConflictError("Generation-3 change-detection comparison facts drifted")

    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection completion integrity failed")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection receipt lifecycle is incomplete")
    expected_rows = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior = None
    for receipt, facts in zip(rows, expected_rows, strict=True):
        sequence, event, occurred_at, decision_hash, completed = facts
        if (
            receipt.sequence_number != sequence
            or receipt.event_type != event
            or receipt.status_after != event
            or receipt.actor_id != execution.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != execution.request_reason
            or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError("Generation-3 change-detection receipt integrity failed")
        for field, expected in _base_safety(completed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Generation-3 change-detection receipt safety boundary drifted")
        prior = receipt.receipt_hash


def execute_external_document_source_generation_3_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    checkpoint_generation_3_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceGeneration3ChangeDetectionExecution).where(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.organization_id == organization_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id == profile_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.request_key == normalized_key,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.checkpoint_generation_3_execution_id != checkpoint_generation_3_execution_id
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for generation-3 change-detection request_key")
        return existing, "unchanged"

    checkpoint = _checkpoint_generation_3(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=checkpoint_generation_3_execution_id,
        for_update=True,
    )
    candidate, observation, listing, item, profile, locator, policy, baseline, baseline_hash = _lineage(db, checkpoint)
    adapter = _OBSERVATION_ADAPTERS.get((profile.provider_kind, policy.observation_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Exact-item generation-3 change-detection adapter is unavailable")
    adapter_kind = _normalize_identifier(adapter.adapter_kind, field="Generation-3 change-detection adapter kind")
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.observation_operation_kind != policy.observation_operation_kind
        or adapter.provider_origin != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError("Generation-3 change-detection adapter policy drifted")

    current = _aware(now or _utc_now())
    endpoint_policy_hash = _endpoint_policy_hash(policy)
    scope_hash = _scope_hash(
        checkpoint,
        observation,
        baseline_projection_hash=baseline_hash,
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution = ExternalDocumentSourceGeneration3ChangeDetectionExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        checkpoint_generation_3_execution_id=checkpoint.id,
        successor_versioned_restaging_execution_id=candidate.id,
        successor_change_detection_execution_id=observation.id,
        predecessor_checkpoint_generation_execution_id=checkpoint.predecessor_checkpoint_generation_execution_id,
        versioned_restaging_execution_id=checkpoint.versioned_restaging_execution_id,
        predecessor_sync_checkpoint_execution_id=checkpoint.predecessor_sync_checkpoint_execution_id,
        change_detection_execution_id=checkpoint.change_detection_execution_id,
        listing_execution_id=checkpoint.listing_execution_id,
        metadata_item_id=checkpoint.metadata_item_id,
        provider_kind=checkpoint.provider_kind,
        profile_hash=checkpoint.profile_hash,
        baseline_generation=GENERATION_3_BASELINE_GENERATION,
        successor_checkpoint_kind=checkpoint.successor_checkpoint_kind,
        successor_checkpoint_state_hash=checkpoint.successor_checkpoint_state_hash,
        successor_checkpoint_completion_hash=checkpoint.completion_hash,
        candidate_content_proof_hash=candidate.content_proof_hash,
        candidate_completion_hash=candidate.completion_hash,
        successor_change_scope_hash=observation.scope_hash,
        successor_change_request_hash=observation.request_hash,
        successor_change_completion_hash=observation.completion_hash,
        baseline_projection_hash=baseline_hash,
        baseline_provider_item_id_hash=baseline["provider_item_id_hash"],
        baseline_item_kind=baseline["item_kind"],
        baseline_display_name_hash=baseline["display_name_hash"],
        baseline_parent_item_id_hash=baseline["parent_item_id_hash"],
        baseline_version_token_hash=baseline["version_token_hash"],
        baseline_byte_size=baseline["byte_size"],
        baseline_modified_at=baseline["modified_at"],
        baseline_mime_type_class=baseline["mime_type_class"],
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
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

    try:
        result = adapter.read_item_metadata(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Exact-item generation-3 metadata observation failed") from None
    observed_projection = _validate_result(result)

    if observed_projection is None:
        execution.result_status = "missing"
        execution.changed_dimensions = "missing"
    else:
        observed = {
            "provider_item_id_hash": hashlib.sha256(observed_projection.provider_item_id.encode("utf-8")).hexdigest(),
            "item_kind": observed_projection.item_kind,
            "display_name_hash": hashlib.sha256(observed_projection.display_name.encode("utf-8")).hexdigest(),
            "parent_item_id_hash": hashlib.sha256(observed_projection.parent_item_id.encode("utf-8")).hexdigest() if observed_projection.parent_item_id is not None else None,
            "mime_type_class": observed_projection.mime_type_class,
            "byte_size": observed_projection.byte_size,
            "modified_at": observed_projection.modified_at,
            "version_token_hash": observed_projection.version_token_hash,
        }
        if observed["provider_item_id_hash"] != baseline["provider_item_id_hash"]:
            raise ExternalDocumentSourceConflictError("Generation-3 exact-item endpoint returned an unexpected provider item identity")
        if observed["item_kind"] != "file":
            raise ExternalDocumentSourceConflictError("Generation-3 exact-item endpoint returned a non-file item")
        changed = _changed_dimensions(baseline, observed)
        execution.result_status = "unchanged" if not changed else "changed"
        execution.observed_projection_hash = _projection_hash(observed)
        execution.observed_provider_item_id_hash = observed["provider_item_id_hash"]
        execution.observed_item_kind = observed["item_kind"]
        execution.observed_display_name_hash = observed["display_name_hash"]
        execution.observed_parent_item_id_hash = observed["parent_item_id_hash"]
        execution.observed_version_token_hash = observed["version_token_hash"]
        execution.observed_byte_size = observed["byte_size"]
        execution.observed_modified_at = observed["modified_at"]
        execution.observed_mime_type_class = observed["mime_type_class"]
        execution.changed_dimensions = ",".join(changed)

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.completed_at = completed_at
    execution.provider_client_constructed = True
    execution.exact_item_metadata_read_performed = True
    execution.generation_3_successor_change_detection_completed = True
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


def get_external_document_source_generation_3_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = db.scalar(
        select(ExternalDocumentSourceGeneration3ChangeDetectionExecution).where(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.id == execution_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.organization_id == organization_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError("Generation-3 change-detection execution not found")
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_generation_3_change_detection_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_generation_3_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
