from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    _OBSERVATION_ADAPTERS,
    _endpoint_policy_hash,
    _normalize_identifier,
    _projection_hash,
    _validate_result,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.evidence_admission_execution_service import (
    _ensure_execution_integrity as _ensure_admission_integrity,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _lock_current_family_document,
    _prior_source_state,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.external_document_sources.generation_3_change_detection_service import (
    _checkpoint_generation_3,
    _ensure_integrity as _ensure_generation3_integrity,
    _lineage as _generation3_lineage,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
    _binding_for_update as _schedule_binding_for_update,
    ensure_recurring_observation_schedule_integrity,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).isoformat()


def _canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
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


def _safety() -> dict[str, bool]:
    return {
        "schedule_authority_verified": True,
        "family_binding_verified": True,
        "current_document_verified": True,
        "provider_lineage_verified": True,
        "due_tick_verified": True,
        "provider_client_constructed": True,
        "exact_item_metadata_read_performed": True,
        "remote_list_performed": False,
        "remote_content_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "document_mutated": False,
        "evidence_admitted": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_worker_started": False,
    }


def _schedule_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    schedule_id: UUID,
    expected_binding_id: UUID,
) -> ExternalDocumentSourceRecurringObservationSchedule:
    # The Y-family binding row is the single serialization authority.
    # Phase AB authorize/replace/disable all acquire that binding FOR UPDATE
    # before mutating schedule state. Holding a second schedule-row lock here
    # creates a binding<->schedule lock cycle with FK checks during AC insert.
    # After the binding lock is held, a plain exact-revision read is stable.
    schedule = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.binding_id
            == expected_binding_id,
        )
    )
    if schedule is None:
        raise ExternalDocumentSourceNotFoundError(
            "Recurring observation schedule not found"
        )
    ensure_recurring_observation_schedule_integrity(db, schedule)
    if schedule.status != "active" or schedule.active_binding_guard != schedule.binding_id:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule is not active"
        )
    return schedule


def _binding(
    db: Session,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> ExternalDocumentSourceEvidenceFamilyBinding:
    binding = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding).where(
            ExternalDocumentSourceEvidenceFamilyBinding.id == schedule.binding_id,
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == schedule.organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id
            == schedule.profile_id,
        )
    )
    if binding is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation Evidence family binding is missing"
        )
    _ensure_binding_integrity(db, binding)
    if (
        binding.claim_id != schedule.claim_id
        or binding.document_family_id != schedule.document_family_id
        or binding.provider_kind != schedule.provider_kind
        or binding.profile_hash != schedule.profile_hash
        or binding.stable_source_item_hash != schedule.stable_source_item_hash
        or binding.completion_hash != schedule.binding_completion_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule family lineage drifted"
        )
    return binding


def _provider_lineage(
    db: Session,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
):
    admission = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionExecution).where(
            ExternalDocumentSourceEvidenceAdmissionExecution.id
            == binding.admission_execution_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.organization_id
            == binding.organization_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.profile_id
            == binding.profile_id,
        )
    )
    if admission is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation initial admission lineage is missing"
        )
    _ensure_admission_integrity(db, admission)

    observation = db.scalar(
        select(ExternalDocumentSourceGeneration3ChangeDetectionExecution).where(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.id
            == admission.generation_3_change_detection_execution_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.organization_id
            == binding.organization_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id
            == binding.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation provider-lineage observation is missing"
        )
    _ensure_generation3_integrity(db, observation)
    if (
        observation.status != "completed"
        or observation.result_status != "unchanged"
        or observation.observed_provider_item_id_hash
        != binding.stable_source_item_hash
        or observation.observed_projection_hash != binding.source_projection_hash
        or observation.completion_hash != binding.source_observation_completion_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation provider lineage drifted"
        )

    checkpoint = _checkpoint_generation_3(
        db,
        organization_id=binding.organization_id,
        profile_id=binding.profile_id,
        execution_id=observation.checkpoint_generation_3_execution_id,
    )
    (
        _candidate,
        _phase_s_observation,
        _listing,
        item,
        profile,
        locator,
        policy,
        _baseline,
        _baseline_hash,
    ) = _generation3_lineage(db, checkpoint)

    if (
        profile.profile_hash != binding.profile_hash
        or profile.provider_kind != binding.provider_kind
        or hashlib.sha256(item.provider_item_id.encode("utf-8")).hexdigest()
        != binding.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation exact-item provider lineage drifted"
        )
    return observation, checkpoint, profile, locator, policy


def _next_due_tick(
    db: Session,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> datetime:
    latest = db.scalar(
        select(ExternalDocumentSourceDueTickObservationExecution.due_at)
        .where(
            ExternalDocumentSourceDueTickObservationExecution.organization_id
            == schedule.organization_id,
            ExternalDocumentSourceDueTickObservationExecution.schedule_id
            == schedule.id,
        )
        .order_by(
            ExternalDocumentSourceDueTickObservationExecution.due_at.desc()
        )
        .limit(1)
    )
    if latest is None:
        return _aware(schedule.effective_at)
    return _aware(latest) + timedelta(minutes=schedule.cadence_minutes)


def _scope_hash(
    *,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    current_document: Document,
    observation: ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    due_at: datetime,
    baseline_projection_hash: str,
    baseline_version_token_hash: str | None,
    observation_operation_kind: str,
    observation_adapter_kind: str,
    endpoint_policy_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(schedule.organization_id),
            "claim_id": str(schedule.claim_id),
            "profile_id": str(schedule.profile_id),
            "schedule_id": str(schedule.id),
            "schedule_authorization_hash": schedule.authorization_hash,
            "schedule_revision_number": schedule.revision_number,
            "binding_id": str(binding.id),
            "binding_completion_hash": binding.completion_hash,
            "document_family_id": str(binding.document_family_id),
            "current_document_id": str(current_document.id),
            "current_version_number": current_document.version_number,
            "provider_lineage_observation_id": str(observation.id),
            "provider_kind": binding.provider_kind,
            "profile_hash": binding.profile_hash,
            "stable_source_item_hash": binding.stable_source_item_hash,
            "cadence_class": schedule.cadence_class,
            "cadence_minutes": schedule.cadence_minutes,
            "due_at": _iso(due_at),
            "baseline_projection_hash": baseline_projection_hash,
            "baseline_version_token_hash": baseline_version_token_hash,
            "observation_operation_kind": observation_operation_kind,
            "observation_adapter_kind": observation_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "request_key": request_key,
        }
    )


def _request_hash(
    execution: ExternalDocumentSourceDueTickObservationExecution,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "executed_by_id": str(execution.executed_by_id),
            "execution_reason": execution.execution_reason,
            "executed_at": _iso(execution.executed_at),
            **_safety(),
        }
    )


def _completion_hash(
    execution: ExternalDocumentSourceDueTickObservationExecution,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "status": execution.status,
            "result_status": execution.result_status,
            "observed_projection_hash": execution.observed_projection_hash,
            "observed_display_name_hash": execution.observed_display_name_hash,
            "observed_version_token_hash": execution.observed_version_token_hash,
            "observed_byte_size": execution.observed_byte_size,
            "observed_modified_at": _iso(execution.observed_modified_at),
            "observed_mime_type_class": execution.observed_mime_type_class,
            "completed_at": _iso(execution.completed_at),
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceDueTickObservationReceipt) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
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
            **_safety(),
        }
    )


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceDueTickObservationExecution,
) -> list[ExternalDocumentSourceDueTickObservationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceDueTickObservationReceipt).where(
                ExternalDocumentSourceDueTickObservationReceipt.organization_id
                == execution.organization_id,
                ExternalDocumentSourceDueTickObservationReceipt.execution_id
                == execution.id,
            )
        ).all()
    )


def _validate_due_sequence(
    db: Session,
    execution: ExternalDocumentSourceDueTickObservationExecution,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> None:
    ticks = list(
        db.scalars(
            select(ExternalDocumentSourceDueTickObservationExecution.due_at)
            .where(
                ExternalDocumentSourceDueTickObservationExecution.organization_id
                == execution.organization_id,
                ExternalDocumentSourceDueTickObservationExecution.schedule_id
                == schedule.id,
                ExternalDocumentSourceDueTickObservationExecution.due_at
                <= execution.due_at,
            )
            .order_by(ExternalDocumentSourceDueTickObservationExecution.due_at.asc())
        ).all()
    )
    if not ticks:
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation sequence is missing"
        )
    expected = _aware(schedule.effective_at)
    for tick in ticks:
        if _aware(tick) != expected:
            raise ExternalDocumentSourceConflictError(
                "Due-tick observation sequence contains a skipped or altered tick"
            )
        expected += timedelta(minutes=schedule.cadence_minutes)
    if _aware(ticks[-1]) != _aware(execution.due_at):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation sequence does not terminate at this execution"
        )


def ensure_due_tick_observation_integrity(
    db: Session,
    execution: ExternalDocumentSourceDueTickObservationExecution,
) -> None:
    schedule = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.id
            == execution.schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == execution.organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == execution.profile_id,
        )
    )
    if schedule is None:
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation schedule lineage is missing"
        )
    ensure_recurring_observation_schedule_integrity(db, schedule)

    binding = _binding(db, schedule)
    current_document = db.get(Document, execution.current_document_id)
    if current_document is None:
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation Document lineage is missing"
        )
    baseline_projection_hash, baseline_version_token_hash = _prior_source_state(
        db,
        binding=binding,
        current_document=current_document,
    )
    observation, checkpoint, _profile, _locator, policy = _provider_lineage(
        db, binding
    )

    expected = {
        "claim_id": binding.claim_id,
        "binding_id": binding.id,
        "document_family_id": binding.document_family_id,
        "provider_kind": binding.provider_kind,
        "profile_hash": binding.profile_hash,
        "stable_source_item_hash": binding.stable_source_item_hash,
        "binding_completion_hash": binding.completion_hash,
        "schedule_authorization_hash": schedule.authorization_hash,
        "schedule_revision_number": schedule.revision_number,
        "cadence_class": schedule.cadence_class,
        "cadence_minutes": schedule.cadence_minutes,
        "provider_lineage_observation_id": observation.id,
        "provider_lineage_checkpoint_id": checkpoint.id,
        "baseline_projection_hash": baseline_projection_hash,
        "baseline_version_token_hash": baseline_version_token_hash,
        "observation_operation_kind": policy.observation_operation_kind,
        "endpoint_policy_hash": _endpoint_policy_hash(policy),
        "status": "completed",
    }
    for field, value in expected.items():
        if getattr(execution, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Due-tick observation integrity drifted at {field}"
            )

    if (
        current_document.organization_id != execution.organization_id
        or current_document.claim_id != execution.claim_id
        or current_document.document_family_id != execution.document_family_id
        or current_document.version_number != execution.current_version_number
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation canonical Document lineage drifted"
        )

    _validate_due_sequence(db, execution, schedule)

    expected_scope = _scope_hash(
        schedule=schedule,
        binding=binding,
        current_document=current_document,
        observation=observation,
        due_at=execution.due_at,
        baseline_projection_hash=baseline_projection_hash,
        baseline_version_token_hash=baseline_version_token_hash,
        observation_operation_kind=execution.observation_operation_kind,
        observation_adapter_kind=execution.observation_adapter_kind,
        endpoint_policy_hash=execution.endpoint_policy_hash,
        request_key=execution.request_key,
    )
    if (
        execution.scope_hash != expected_scope
        or execution.request_hash != _request_hash(execution)
        or execution.completion_hash != _completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(execution, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Due-tick observation safety boundary drifted"
            )
    if (
        execution.result_status == "missing"
        and any(
            value is not None
            for value in (
                execution.observed_projection_hash,
                execution.observed_display_name_hash,
                execution.observed_version_token_hash,
                execution.observed_byte_size,
                execution.observed_modified_at,
                execution.observed_mime_type_class,
            )
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Missing due-tick observation unexpectedly persisted remote metadata"
        )
    if (
        execution.result_status in {"unchanged", "changed"}
        and (
            execution.observed_projection_hash is None
            or execution.observed_display_name_hash is None
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Present due-tick observation metadata is incomplete"
        )
    if (
        execution.result_status == "unchanged"
        and execution.observed_projection_hash != execution.baseline_projection_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Unchanged due-tick observation does not match baseline"
        )
    if (
        execution.result_status == "changed"
        and execution.observed_projection_hash == execution.baseline_projection_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Changed due-tick observation still matches baseline"
        )
    if _aware(execution.completed_at) < _aware(execution.executed_at):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation timestamps drifted"
        )

    receipts = _receipts(db, execution)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "completed"
        or receipt.status_after != "completed"
        or receipt.actor_id != execution.executed_by_id
        or _aware(receipt.occurred_at) != _aware(execution.completed_at)
        or receipt.reason != execution.execution_reason
        or receipt.scope_hash != execution.scope_hash
        or receipt.decision_hash != execution.completion_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Due-tick observation receipt safety boundary drifted"
            )


def execute_due_tick_observation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    schedule_id: UUID,
    executed_by_id: UUID,
    request_key: str,
    reason: str,
    now: datetime | None = None,
) -> tuple[ExternalDocumentSourceDueTickObservationExecution, str]:
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        reason, field="reason", minimum=20, maximum=2000
    )

    existing = db.scalar(
        select(ExternalDocumentSourceDueTickObservationExecution).where(
            ExternalDocumentSourceDueTickObservationExecution.organization_id
            == organization_id,
            ExternalDocumentSourceDueTickObservationExecution.profile_id
            == profile_id,
            ExternalDocumentSourceDueTickObservationExecution.request_key
            == normalized_key,
        )
    )
    if existing is not None:
        ensure_due_tick_observation_integrity(db, existing)
        if (
            existing.schedule_id != schedule_id
            or existing.executed_by_id != executed_by_id
            or existing.execution_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Due-tick observation request key was already used with different inputs"
            )
        return existing, "replayed"

    schedule_snapshot = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
        )
    )
    if schedule_snapshot is None:
        raise ExternalDocumentSourceNotFoundError(
            "Recurring observation schedule not found"
        )

    # Match Phase-AB transition lock ordering exactly: family binding first,
    # then the exact schedule revision, then the canonical current Document.
    # This serializes consume-vs-disable/replace without a lock inversion.
    binding = _schedule_binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=schedule_snapshot.binding_id,
    )
    schedule = _schedule_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        schedule_id=schedule_id,
        expected_binding_id=binding.id,
    )
    verified_binding = _binding(db, schedule)
    if verified_binding.id != binding.id:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule binding changed while acquiring authority"
        )
    current_document = _lock_current_family_document(
        db,
        organization_id=organization_id,
        claim_id=binding.claim_id,
        document_family_id=binding.document_family_id,
    )
    baseline_projection_hash, baseline_version_token_hash = _prior_source_state(
        db,
        binding=binding,
        current_document=current_document,
    )

    due_at = _next_due_tick(db, schedule)
    current_time = _aware(now or _utc_now())
    if due_at > current_time:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule is not due yet"
        )

    observation, checkpoint, profile, locator, policy = _provider_lineage(db, binding)
    adapter = _OBSERVATION_ADAPTERS.get(
        (profile.provider_kind, policy.observation_operation_kind)
    )
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "Exact-item metadata adapter is unavailable for due-tick observation"
        )
    adapter_kind = _normalize_identifier(
        adapter.adapter_kind,
        field="Due-tick observation adapter kind",
    )
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.observation_operation_kind != policy.observation_operation_kind
        or adapter.provider_origin != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation adapter policy drifted"
        )
    endpoint_policy_hash = _endpoint_policy_hash(policy)

    try:
        result = adapter.read_item_metadata(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "Due-tick exact-item metadata observation failed"
        ) from None
    projection = _validate_result(result)

    result_status: str
    observed_projection_hash: str | None = None
    observed_display_name_hash: str | None = None
    observed_version_token_hash: str | None = None
    observed_byte_size: int | None = None
    observed_modified_at: datetime | None = None
    observed_mime_type_class: str | None = None

    if projection is None:
        result_status = "missing"
    else:
        provider_item_id_hash = hashlib.sha256(
            projection.provider_item_id.encode("utf-8")
        ).hexdigest()
        if provider_item_id_hash != binding.stable_source_item_hash:
            raise ExternalDocumentSourceConflictError(
                "Due-tick observation returned a different provider item"
            )
        if projection.item_kind != "file":
            raise ExternalDocumentSourceConflictError(
                "Due-tick observation source is no longer a file"
            )
        facts = {
            "provider_item_id_hash": provider_item_id_hash,
            "item_kind": projection.item_kind,
            "display_name_hash": hashlib.sha256(
                projection.display_name.encode("utf-8")
            ).hexdigest(),
            "parent_item_id_hash": (
                hashlib.sha256(
                    projection.parent_item_id.encode("utf-8")
                ).hexdigest()
                if projection.parent_item_id is not None
                else None
            ),
            "mime_type_class": projection.mime_type_class,
            "byte_size": projection.byte_size,
            "modified_at": projection.modified_at,
            "version_token_hash": projection.version_token_hash,
        }
        observed_projection_hash = _projection_hash(facts)
        observed_display_name_hash = facts["display_name_hash"]
        observed_version_token_hash = facts["version_token_hash"]
        observed_byte_size = facts["byte_size"]
        observed_modified_at = facts["modified_at"]
        observed_mime_type_class = facts["mime_type_class"]
        result_status = (
            "unchanged"
            if observed_projection_hash == baseline_projection_hash
            else "changed"
        )

    executed_at = current_time
    completed_at = max(current_time, _utc_now())
    execution = ExternalDocumentSourceDueTickObservationExecution(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=binding.claim_id,
        profile_id=profile_id,
        schedule_id=schedule.id,
        binding_id=binding.id,
        document_family_id=binding.document_family_id,
        current_document_id=current_document.id,
        current_version_number=current_document.version_number,
        provider_lineage_observation_id=observation.id,
        provider_lineage_checkpoint_id=checkpoint.id,
        provider_kind=binding.provider_kind,
        profile_hash=binding.profile_hash,
        stable_source_item_hash=binding.stable_source_item_hash,
        binding_completion_hash=binding.completion_hash,
        schedule_authorization_hash=schedule.authorization_hash,
        schedule_revision_number=schedule.revision_number,
        cadence_class=schedule.cadence_class,
        cadence_minutes=schedule.cadence_minutes,
        due_at=due_at,
        baseline_projection_hash=baseline_projection_hash,
        baseline_version_token_hash=baseline_version_token_hash,
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        result_status=result_status,
        observed_projection_hash=observed_projection_hash,
        observed_display_name_hash=observed_display_name_hash,
        observed_version_token_hash=observed_version_token_hash,
        observed_byte_size=observed_byte_size,
        observed_modified_at=observed_modified_at,
        observed_mime_type_class=observed_mime_type_class,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="completed",
        executed_by_id=executed_by_id,
        execution_reason=normalized_reason,
        executed_at=executed_at,
        completed_at=completed_at,
        completion_hash="",
        **_safety(),
    )
    execution.scope_hash = _scope_hash(
        schedule=schedule,
        binding=binding,
        current_document=current_document,
        observation=observation,
        due_at=due_at,
        baseline_projection_hash=baseline_projection_hash,
        baseline_version_token_hash=baseline_version_token_hash,
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution.request_hash = _request_hash(execution)
    execution.completion_hash = _completion_hash(execution)
    db.add(execution)
    db.flush()

    receipt = ExternalDocumentSourceDueTickObservationReceipt(
        id=uuid4(),
        organization_id=organization_id,
        execution_id=execution.id,
        sequence_number=1,
        event_type="completed",
        status_after="completed",
        actor_id=executed_by_id,
        occurred_at=completed_at,
        reason=normalized_reason,
        scope_hash=execution.scope_hash,
        decision_hash=execution.completion_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    ensure_due_tick_observation_integrity(db, execution)

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=executed_by_id,
        action="EXECUTE_EXTERNAL_EVIDENCE_DUE_TICK_OBSERVATION",
        entity_type="external_document_source_due_tick_observation",
        entity_id=execution.id,
        new_values={
            "claim_id": str(binding.claim_id),
            "schedule_id": str(schedule.id),
            "schedule_revision_number": schedule.revision_number,
            "binding_id": str(binding.id),
            "document_family_id": str(binding.document_family_id),
            "current_document_id": str(current_document.id),
            "current_version_number": current_document.version_number,
            "due_at": _iso(due_at),
            "result_status": result_status,
            "remote_content_read_performed": False,
            "document_mutated": False,
            "processing_enqueued": False,
            "ai_executed": False,
        },
    )
    db.commit()
    db.refresh(execution)
    return execution, "completed"


def get_due_tick_observation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceDueTickObservationExecution:
    execution = db.scalar(
        select(ExternalDocumentSourceDueTickObservationExecution).where(
            ExternalDocumentSourceDueTickObservationExecution.id == execution_id,
            ExternalDocumentSourceDueTickObservationExecution.organization_id
            == organization_id,
            ExternalDocumentSourceDueTickObservationExecution.profile_id
            == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError(
            "Due-tick observation execution not found"
        )
    ensure_due_tick_observation_integrity(db, execution)
    return execution


def list_due_tick_observation_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> list[ExternalDocumentSourceDueTickObservationReceipt]:
    execution = get_due_tick_observation(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
