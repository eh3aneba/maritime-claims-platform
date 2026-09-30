from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    ensure_due_tick_observation_integrity,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _binding_for_update,
    _lock_current_family_document,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    ensure_observation_refresh_admission_execution_integrity,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    ensure_observation_refresh_execution_integrity,
)
from app.modules.external_document_sources.recurring_baseline_transition_models import (
    ExternalDocumentSourceRecurringBaselineTransition,
    ExternalDocumentSourceRecurringBaselineTransitionReceipt,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
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


def _iso(value: datetime) -> str:
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


def _safety() -> dict[str, bool]:
    return {
        "refresh_admission_verified": True,
        "refresh_execution_verified": True,
        "originating_observation_verified": True,
        "family_binding_verified": True,
        "stable_source_identity_verified": True,
        "current_document_verified": True,
        "schedule_authority_verified": True,
        "human_authorization_recorded": True,
        "recurring_baseline_established": True,
        "provider_client_constructed": False,
        "remote_metadata_read_performed": False,
        "remote_content_read_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "document_mutated": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_mutated": False,
        "schedule_mutated": False,
    }


def _scope_hash(
    *,
    admission: ExternalDocumentSourceObservationRefreshAdmissionExecution,
    refresh: ExternalDocumentSourceObservationRefreshExecution,
    observation: ExternalDocumentSourceDueTickObservationExecution,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
    binding_completion_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(admission.organization_id),
            "claim_id": str(admission.claim_id),
            "profile_id": str(admission.profile_id),
            "binding_id": str(admission.binding_id),
            "document_family_id": str(admission.document_family_id),
            "schedule_id": str(schedule.id),
            "schedule_revision_number": schedule.revision_number,
            "schedule_authorization_hash": schedule.authorization_hash,
            "refresh_admission_execution_id": str(admission.id),
            "refresh_admission_completion_hash": admission.completion_hash,
            "refresh_execution_id": str(refresh.id),
            "refresh_completion_hash": refresh.completion_hash,
            "originating_observation_execution_id": str(observation.id),
            "originating_observation_completion_hash": observation.completion_hash,
            "prior_document_id": str(admission.prior_document_id),
            "current_document_id": str(admission.new_document_id),
            "current_version_number": admission.new_version_number,
            "provider_kind": admission.provider_kind,
            "profile_hash": admission.profile_hash,
            "stable_source_item_hash": admission.stable_source_item_hash,
            "binding_completion_hash": binding_completion_hash,
            "baseline_projection_hash": refresh.observed_projection_hash,
            "baseline_version_token_hash": refresh.observed_version_token_hash,
            "refreshed_content_sha256": admission.refreshed_content_sha256,
            "refreshed_content_proof_hash": admission.refreshed_content_proof_hash,
            "request_key": request_key,
        }
    )


def _request_hash(
    transition: ExternalDocumentSourceRecurringBaselineTransition,
) -> str:
    return _canonical_hash(
        {
            "transition_id": str(transition.id),
            "scope_hash": transition.scope_hash,
            "authorized_by_id": str(transition.authorized_by_id),
            "authorization_reason": transition.authorization_reason,
            "authorized_at": _iso(transition.authorized_at),
            **_safety(),
        }
    )


def _completion_hash(
    transition: ExternalDocumentSourceRecurringBaselineTransition,
) -> str:
    return _canonical_hash(
        {
            "transition_id": str(transition.id),
            "scope_hash": transition.scope_hash,
            "request_hash": transition.request_hash,
            "status": transition.status,
            "current_document_id": str(transition.current_document_id),
            "current_version_number": transition.current_version_number,
            "baseline_projection_hash": transition.baseline_projection_hash,
            "baseline_version_token_hash": transition.baseline_version_token_hash,
            "refresh_admission_completion_hash": transition.refresh_admission_completion_hash,
            "refresh_completion_hash": transition.refresh_completion_hash,
            "originating_observation_completion_hash": transition.originating_observation_completion_hash,
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceRecurringBaselineTransitionReceipt,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "transition_id": str(receipt.transition_id),
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


def ensure_recurring_baseline_transition_integrity(
    db: Session,
    transition: ExternalDocumentSourceRecurringBaselineTransition,
) -> None:
    admission = db.get(
        ExternalDocumentSourceObservationRefreshAdmissionExecution,
        transition.refresh_admission_execution_id,
    )
    if admission is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition refresh admission is missing"
        )
    ensure_observation_refresh_admission_execution_integrity(db, admission)

    refresh = db.get(
        ExternalDocumentSourceObservationRefreshExecution,
        transition.refresh_execution_id,
    )
    if refresh is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition refresh execution is missing"
        )
    ensure_observation_refresh_execution_integrity(db, refresh, verify_storage=False)

    observation = db.get(
        ExternalDocumentSourceDueTickObservationExecution,
        transition.originating_observation_execution_id,
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition originating observation is missing"
        )
    ensure_due_tick_observation_integrity(db, observation)

    binding = _binding_for_update(
        db,
        organization_id=transition.organization_id,
        profile_id=transition.profile_id,
        binding_id=transition.binding_id,
    )
    _ensure_binding_integrity(db, binding)

    schedule = db.get(
        ExternalDocumentSourceRecurringObservationSchedule,
        transition.schedule_id,
    )
    if schedule is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition schedule is missing"
        )
    ensure_recurring_observation_schedule_integrity(db, schedule)

    current = db.get(Document, transition.current_document_id)
    prior = db.get(Document, transition.prior_document_id)
    if current is None or prior is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition Document lineage is missing"
        )

    expected = {
        "claim_id": admission.claim_id,
        "profile_id": admission.profile_id,
        "binding_id": admission.binding_id,
        "document_family_id": admission.document_family_id,
        "schedule_id": observation.schedule_id,
        "schedule_revision_number": observation.schedule_revision_number,
        "refresh_execution_id": admission.refresh_execution_id,
        "originating_observation_execution_id": refresh.observation_execution_id,
        "prior_document_id": admission.prior_document_id,
        "current_document_id": admission.new_document_id,
        "current_version_number": admission.new_version_number,
        "provider_kind": admission.provider_kind,
        "profile_hash": admission.profile_hash,
        "stable_source_item_hash": admission.stable_source_item_hash,
        "binding_completion_hash": admission.binding_completion_hash,
        "schedule_authorization_hash": observation.schedule_authorization_hash,
        "refresh_admission_completion_hash": admission.completion_hash,
        "refresh_completion_hash": refresh.completion_hash,
        "originating_observation_completion_hash": observation.completion_hash,
        "baseline_projection_hash": refresh.observed_projection_hash,
        "baseline_version_token_hash": refresh.observed_version_token_hash,
        "refreshed_content_sha256": admission.refreshed_content_sha256,
        "refreshed_content_proof_hash": admission.refreshed_content_proof_hash,
        "status": "established",
    }
    for field, value in expected.items():
        if getattr(transition, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Recurring baseline transition snapshot drifted at {field}"
            )

    if (
        transition.provider_kind != "sftp"
        or refresh.result_status != "staged_refresh_verified"
        or refresh.observed_projection_hash is None
        or observation.result_status != "changed"
        or admission.provider_kind != "sftp"
        or schedule.status != "active"
        or schedule.active_binding_guard != binding.id
        or schedule.binding_id != binding.id
        or schedule.authorization_hash != transition.schedule_authorization_hash
        or current.id != admission.new_document_id
        or not current.is_current
        or current.version_number != admission.new_version_number
        or current.document_family_id != binding.document_family_id
        or current.file_hash != admission.refreshed_content_sha256
        or prior.id != admission.prior_document_id
        or prior.is_current
        or prior.document_family_id != binding.document_family_id
        or transition.scope_hash
        != _scope_hash(
            admission=admission,
            refresh=refresh,
            observation=observation,
            schedule=schedule,
            binding_completion_hash=binding.completion_hash,
            request_key=transition.request_key,
        )
        or transition.request_hash != _request_hash(transition)
        or transition.completion_hash != _completion_hash(transition)
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition cryptographic or authority integrity failed"
        )

    for field, value in _safety().items():
        if bool(getattr(transition, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Recurring baseline transition safety boundary drifted"
            )

    receipts = list(
        db.scalars(
            select(ExternalDocumentSourceRecurringBaselineTransitionReceipt).where(
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.organization_id
                == transition.organization_id,
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.transition_id
                == transition.id,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "established"
        or receipt.status_after != "established"
        or receipt.actor_id != transition.authorized_by_id
        or _aware(receipt.occurred_at) != _aware(transition.authorized_at)
        or receipt.reason != transition.authorization_reason
        or receipt.scope_hash != transition.scope_hash
        or receipt.decision_hash != transition.completion_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Recurring baseline transition receipt safety boundary drifted"
            )


def establish_recurring_baseline_transition(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    refresh_admission_execution_id: UUID,
    authorized_by_id: UUID,
    request_key: str,
    reason: str,
    now: datetime | None = None,
) -> tuple[ExternalDocumentSourceRecurringBaselineTransition, str]:
    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        reason,
        field="reason",
        minimum=8,
        maximum=1000,
    )

    existing_request = db.scalar(
        select(ExternalDocumentSourceRecurringBaselineTransition).where(
            ExternalDocumentSourceRecurringBaselineTransition.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringBaselineTransition.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringBaselineTransition.request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_recurring_baseline_transition_integrity(db, existing_request)
        if (
            existing_request.refresh_admission_execution_id
            != refresh_admission_execution_id
            or existing_request.authorized_by_id != authorized_by_id
            or existing_request.authorization_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Recurring baseline transition request key was already used with different inputs"
            )
        return existing_request, "replayed"

    admission = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionExecution)
        .where(
            ExternalDocumentSourceObservationRefreshAdmissionExecution.id
            == refresh_admission_execution_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if admission is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation refresh admission execution not found"
        )
    ensure_observation_refresh_admission_execution_integrity(db, admission)
    if admission.provider_kind != "sftp" or admission.status != "admitted":
        raise ExternalDocumentSourceConflictError(
            "Recurring baseline transition requires an admitted SFTP refresh"
        )

    existing_admission = db.scalar(
        select(ExternalDocumentSourceRecurringBaselineTransition).where(
            ExternalDocumentSourceRecurringBaselineTransition.refresh_admission_execution_id
            == admission.id
        )
    )
    if existing_admission is not None:
        ensure_recurring_baseline_transition_integrity(db, existing_admission)
        raise ExternalDocumentSourceConflictError(
            "This SFTP refresh admission already has a recurring baseline transition"
        )

    refresh = db.get(
        ExternalDocumentSourceObservationRefreshExecution,
        admission.refresh_execution_id,
    )
    if refresh is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP refresh execution lineage is missing"
        )
    ensure_observation_refresh_execution_integrity(db, refresh, verify_storage=False)
    if (
        refresh.provider_kind != "sftp"
        or refresh.result_status != "staged_refresh_verified"
        or refresh.observed_projection_hash is None
        or refresh.content_sha256 != admission.refreshed_content_sha256
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP refresh execution is not eligible for recurring baseline transition"
        )

    observation = db.get(
        ExternalDocumentSourceDueTickObservationExecution,
        refresh.observation_execution_id,
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP refresh originating observation is missing"
        )
    ensure_due_tick_observation_integrity(db, observation)
    if (
        observation.provider_kind != "sftp"
        or observation.result_status != "changed"
        or observation.observed_projection_hash != refresh.observed_projection_hash
        or observation.observed_version_token_hash != refresh.observed_version_token_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP refresh originating changed observation drifted"
        )

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=admission.binding_id,
    )
    _ensure_binding_integrity(db, binding)
    current = _lock_current_family_document(
        db,
        organization_id=organization_id,
        claim_id=admission.claim_id,
        document_family_id=admission.document_family_id,
        expected_current_document_id=admission.new_document_id,
    )
    if (
        binding.status != "active"
        or binding.provider_kind != "sftp"
        or binding.claim_id != admission.claim_id
        or binding.document_family_id != admission.document_family_id
        or binding.profile_hash != admission.profile_hash
        or binding.stable_source_item_hash != admission.stable_source_item_hash
        or binding.completion_hash != admission.binding_completion_hash
        or current.version_number != admission.new_version_number
        or current.file_hash != admission.refreshed_content_sha256
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP refreshed Evidence family authority drifted"
        )

    schedule = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule)
        .where(
            ExternalDocumentSourceRecurringObservationSchedule.id
            == observation.schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if schedule is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring schedule lineage is missing"
        )
    ensure_recurring_observation_schedule_integrity(db, schedule)
    if (
        schedule.status != "active"
        or schedule.active_binding_guard != binding.id
        or schedule.binding_id != binding.id
        or schedule.revision_number != observation.schedule_revision_number
        or schedule.authorization_hash != observation.schedule_authorization_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring schedule changed before baseline transition"
        )

    authorized_at = _aware(now or _utc_now())
    transition = ExternalDocumentSourceRecurringBaselineTransition(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=admission.claim_id,
        profile_id=profile_id,
        binding_id=binding.id,
        document_family_id=binding.document_family_id,
        schedule_id=schedule.id,
        schedule_revision_number=schedule.revision_number,
        refresh_admission_execution_id=admission.id,
        refresh_execution_id=refresh.id,
        originating_observation_execution_id=observation.id,
        prior_document_id=admission.prior_document_id,
        current_document_id=current.id,
        current_version_number=current.version_number,
        provider_kind="sftp",
        profile_hash=binding.profile_hash,
        stable_source_item_hash=binding.stable_source_item_hash,
        binding_completion_hash=binding.completion_hash,
        schedule_authorization_hash=schedule.authorization_hash,
        refresh_admission_completion_hash=admission.completion_hash,
        refresh_completion_hash=refresh.completion_hash,
        originating_observation_completion_hash=observation.completion_hash,
        baseline_projection_hash=refresh.observed_projection_hash,
        baseline_version_token_hash=refresh.observed_version_token_hash,
        refreshed_content_sha256=admission.refreshed_content_sha256,
        refreshed_content_proof_hash=admission.refreshed_content_proof_hash,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="established",
        authorized_by_id=authorized_by_id,
        authorization_reason=normalized_reason,
        authorized_at=authorized_at,
        completion_hash="",
        **_safety(),
    )
    transition.scope_hash = _scope_hash(
        admission=admission,
        refresh=refresh,
        observation=observation,
        schedule=schedule,
        binding_completion_hash=binding.completion_hash,
        request_key=normalized_key,
    )
    transition.request_hash = _request_hash(transition)
    transition.completion_hash = _completion_hash(transition)
    db.add(transition)
    db.flush()

    receipt = ExternalDocumentSourceRecurringBaselineTransitionReceipt(
        id=uuid4(),
        organization_id=organization_id,
        transition_id=transition.id,
        sequence_number=1,
        event_type="established",
        status_after="established",
        actor_id=authorized_by_id,
        occurred_at=authorized_at,
        reason=normalized_reason,
        scope_hash=transition.scope_hash,
        decision_hash=transition.completion_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()

    ensure_recurring_baseline_transition_integrity(db, transition)

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=authorized_by_id,
        action="ESTABLISH_EXTERNAL_EVIDENCE_RECURRING_BASELINE",
        entity_type="external_document_source_recurring_baseline_transition",
        entity_id=transition.id,
        new_values={
            "claim_id": str(transition.claim_id),
            "binding_id": str(transition.binding_id),
            "document_family_id": str(transition.document_family_id),
            "schedule_id": str(transition.schedule_id),
            "refresh_admission_execution_id": str(transition.refresh_admission_execution_id),
            "current_document_id": str(transition.current_document_id),
            "current_version_number": transition.current_version_number,
            "provider_kind": transition.provider_kind,
            "profile_hash": transition.profile_hash,
            "stable_source_item_hash": transition.stable_source_item_hash,
            "baseline_projection_hash": transition.baseline_projection_hash,
            "baseline_version_token_hash": transition.baseline_version_token_hash,
            "provider_io_performed": False,
            "storage_io_performed": False,
            "document_mutated": False,
            "processing_enqueued": False,
            "ai_executed": False,
            "checkpoint_mutated": False,
            "schedule_mutated": False,
        },
        change_summary=(
            "A human-controlled immutable transition established the trusted recurring "
            "observation baseline for the exact newly admitted SFTP Evidence version. "
            "No provider, storage, Document, processing, AI, schedule or checkpoint "
            "mutation was performed by the transition itself."
        ),
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(transition)
    return transition, "established"


def get_recurring_baseline_transition(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    transition_id: UUID,
) -> ExternalDocumentSourceRecurringBaselineTransition:
    transition = db.scalar(
        select(ExternalDocumentSourceRecurringBaselineTransition).where(
            ExternalDocumentSourceRecurringBaselineTransition.id == transition_id,
            ExternalDocumentSourceRecurringBaselineTransition.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringBaselineTransition.profile_id == profile_id,
        )
    )
    if transition is None:
        raise ExternalDocumentSourceNotFoundError(
            "Recurring baseline transition not found"
        )
    ensure_recurring_baseline_transition_integrity(db, transition)
    return transition


def list_recurring_baseline_transition_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    transition_id: UUID,
) -> list[ExternalDocumentSourceRecurringBaselineTransitionReceipt]:
    transition = get_recurring_baseline_transition(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        transition_id=transition_id,
    )
    return list(
        db.scalars(
            select(ExternalDocumentSourceRecurringBaselineTransitionReceipt)
            .where(
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.organization_id
                == organization_id,
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.transition_id
                == transition.id,
            )
            .order_by(
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.sequence_number
            )
        ).all()
    )
