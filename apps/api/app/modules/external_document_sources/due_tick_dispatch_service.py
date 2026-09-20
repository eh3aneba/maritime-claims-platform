from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
    ExternalDocumentSourceDueTickDispatchReceipt,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    _binding as _verified_binding,
    _next_due_tick,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _lock_current_family_document,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
    _binding_for_update as _schedule_binding_for_update,
    ensure_recurring_observation_schedule_integrity,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError


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
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _worker_hash(worker_id: str) -> str:
    normalized = " ".join(worker_id.strip().split())
    if not normalized or len(normalized) > 128 or "\x00" in normalized:
        raise ValueError("worker_id must contain between 1 and 128 safe characters")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safety() -> dict[str, bool]:
    return {
        "schedule_authority_verified": True,
        "family_binding_verified": True,
        "current_document_verified": True,
        "due_tick_verified": True,
        "internal_worker_identity_recorded": True,
        "db_only_dispatch_verified": True,
        "provider_client_constructed": False,
        "token_acquired": False,
        "remote_metadata_read_performed": False,
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
    }


def _scope_hash(dispatch: ExternalDocumentSourceDueTickDispatch) -> str:
    return _canonical_hash(
        {
            "organization_id": str(dispatch.organization_id),
            "claim_id": str(dispatch.claim_id),
            "profile_id": str(dispatch.profile_id),
            "schedule_id": str(dispatch.schedule_id),
            "binding_id": str(dispatch.binding_id),
            "document_family_id": str(dispatch.document_family_id),
            "current_document_id": str(dispatch.current_document_id),
            "current_version_number": dispatch.current_version_number,
            "schedule_revision_number": dispatch.schedule_revision_number,
            "schedule_authorization_hash": dispatch.schedule_authorization_hash,
            "binding_completion_hash": dispatch.binding_completion_hash,
            "provider_kind": dispatch.provider_kind,
            "profile_hash": dispatch.profile_hash,
            "stable_source_item_hash": dispatch.stable_source_item_hash,
            "cadence_class": dispatch.cadence_class,
            "cadence_minutes": dispatch.cadence_minutes,
            "due_at": _iso(dispatch.due_at),
            "worker_id_hash": dispatch.worker_id_hash,
        }
    )


def _completion_hash(dispatch: ExternalDocumentSourceDueTickDispatch) -> str:
    return _canonical_hash(
        {
            "dispatch_id": str(dispatch.id),
            "scope_hash": dispatch.scope_hash,
            "status": dispatch.status,
            "dispatched_at": _iso(dispatch.dispatched_at),
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceDueTickDispatchReceipt) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "dispatch_id": str(receipt.dispatch_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "worker_id_hash": receipt.worker_id_hash,
            "occurred_at": _iso(receipt.occurred_at),
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            **_safety(),
        }
    )


def ensure_due_tick_dispatch_integrity(
    db: Session,
    dispatch: ExternalDocumentSourceDueTickDispatch,
) -> None:
    if dispatch.status != "dispatched":
        raise ExternalDocumentSourceConflictError("Due-tick dispatch status drifted")
    if dispatch.scope_hash != _scope_hash(dispatch):
        raise ExternalDocumentSourceConflictError("Due-tick dispatch scope integrity drifted")
    if dispatch.completion_hash != _completion_hash(dispatch):
        raise ExternalDocumentSourceConflictError("Due-tick dispatch completion integrity drifted")
    for field, value in _safety().items():
        if bool(getattr(dispatch, field)) != value:
            raise ExternalDocumentSourceConflictError("Due-tick dispatch safety boundary drifted")

    receipts = list(
        db.scalars(
            select(ExternalDocumentSourceDueTickDispatchReceipt).where(
                ExternalDocumentSourceDueTickDispatchReceipt.organization_id == dispatch.organization_id,
                ExternalDocumentSourceDueTickDispatchReceipt.dispatch_id == dispatch.id,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError("Due-tick dispatch receipt lifecycle drifted")
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "dispatched"
        or receipt.status_after != "dispatched"
        or receipt.worker_id_hash != dispatch.worker_id_hash
        or _aware(receipt.occurred_at) != _aware(dispatch.dispatched_at)
        or receipt.scope_hash != dispatch.scope_hash
        or receipt.decision_hash != dispatch.completion_hash
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError("Due-tick dispatch receipt integrity drifted")
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError("Due-tick dispatch receipt safety boundary drifted")


def dispatch_next_due_tick(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    candidate_limit: int = 256,
) -> ExternalDocumentSourceDueTickDispatch | None:
    if candidate_limit < 1 or candidate_limit > 1000:
        raise ValueError("candidate_limit must be between 1 and 1000")
    worker_id_hash = _worker_hash(worker_id)
    current_time = _aware(now or _utc_now())

    candidate_ids = list(
        db.scalars(
            select(ExternalDocumentSourceRecurringObservationSchedule.id)
            .where(
                ExternalDocumentSourceRecurringObservationSchedule.status == "active",
                ExternalDocumentSourceRecurringObservationSchedule.next_due_at <= current_time,
            )
            .order_by(
                ExternalDocumentSourceRecurringObservationSchedule.next_due_at,
                ExternalDocumentSourceRecurringObservationSchedule.id,
            )
            .limit(candidate_limit)
        ).all()
    )

    for schedule_id in candidate_ids:
        snapshot = db.get(ExternalDocumentSourceRecurringObservationSchedule, schedule_id)
        if snapshot is None:
            continue

        binding = _schedule_binding_for_update(
            db,
            organization_id=snapshot.organization_id,
            profile_id=snapshot.profile_id,
            binding_id=snapshot.binding_id,
        )
        schedule = db.get(ExternalDocumentSourceRecurringObservationSchedule, schedule_id)
        if schedule is None:
            raise ExternalDocumentSourceConflictError("Recurring observation schedule disappeared during dispatch")
        ensure_recurring_observation_schedule_integrity(db, schedule)
        if schedule.status != "active" or schedule.active_binding_guard != schedule.binding_id:
            continue

        verified_binding = _verified_binding(db, schedule)
        if verified_binding.id != binding.id:
            raise ExternalDocumentSourceConflictError("Due-tick dispatch family binding drifted")

        current_document = _lock_current_family_document(
            db,
            organization_id=schedule.organization_id,
            claim_id=schedule.claim_id,
            document_family_id=schedule.document_family_id,
        )
        due_at = _next_due_tick(db, schedule)
        if due_at > current_time:
            continue

        already_completed = db.scalar(
            select(ExternalDocumentSourceDueTickObservationExecution.id).where(
                ExternalDocumentSourceDueTickObservationExecution.organization_id == schedule.organization_id,
                ExternalDocumentSourceDueTickObservationExecution.schedule_id == schedule.id,
                ExternalDocumentSourceDueTickObservationExecution.due_at == due_at,
            )
        )
        if already_completed is not None:
            continue

        existing = db.scalar(
            select(ExternalDocumentSourceDueTickDispatch).where(
                ExternalDocumentSourceDueTickDispatch.organization_id == schedule.organization_id,
                ExternalDocumentSourceDueTickDispatch.schedule_id == schedule.id,
                ExternalDocumentSourceDueTickDispatch.due_at == due_at,
            )
        )
        if existing is not None:
            ensure_due_tick_dispatch_integrity(db, existing)
            continue

        dispatched_at = current_time
        dispatch = ExternalDocumentSourceDueTickDispatch(
            id=uuid4(),
            organization_id=schedule.organization_id,
            claim_id=schedule.claim_id,
            profile_id=schedule.profile_id,
            schedule_id=schedule.id,
            binding_id=binding.id,
            document_family_id=schedule.document_family_id,
            current_document_id=current_document.id,
            current_version_number=current_document.version_number,
            schedule_revision_number=schedule.revision_number,
            schedule_authorization_hash=schedule.authorization_hash,
            binding_completion_hash=binding.completion_hash,
            provider_kind=schedule.provider_kind,
            profile_hash=schedule.profile_hash,
            stable_source_item_hash=schedule.stable_source_item_hash,
            cadence_class=schedule.cadence_class,
            cadence_minutes=schedule.cadence_minutes,
            due_at=due_at,
            worker_id_hash=worker_id_hash,
            status="dispatched",
            dispatched_at=dispatched_at,
            scope_hash="",
            completion_hash="",
            **_safety(),
        )
        dispatch.scope_hash = _scope_hash(dispatch)
        dispatch.completion_hash = _completion_hash(dispatch)
        db.add(dispatch)
        db.flush()

        receipt = ExternalDocumentSourceDueTickDispatchReceipt(
            id=uuid4(),
            organization_id=schedule.organization_id,
            dispatch_id=dispatch.id,
            sequence_number=1,
            event_type="dispatched",
            status_after="dispatched",
            worker_id_hash=worker_id_hash,
            occurred_at=dispatched_at,
            scope_hash=dispatch.scope_hash,
            decision_hash=dispatch.completion_hash,
            receipt_hash="",
            **_safety(),
        )
        receipt.receipt_hash = _receipt_hash(receipt)
        db.add(receipt)
        db.flush()
        ensure_due_tick_dispatch_integrity(db, dispatch)

        write_audit_log(
            db,
            organization_id=schedule.organization_id,
            user_id=None,
            action="DISPATCH_EXTERNAL_EVIDENCE_DUE_TICK",
            entity_type="external_document_source_due_tick_dispatch",
            entity_id=dispatch.id,
            new_values={
                "claim_id": str(schedule.claim_id),
                "profile_id": str(schedule.profile_id),
                "schedule_id": str(schedule.id),
                "schedule_revision_number": schedule.revision_number,
                "binding_id": str(binding.id),
                "document_family_id": str(schedule.document_family_id),
                "current_document_id": str(current_document.id),
                "current_version_number": current_document.version_number,
                "due_at": _iso(due_at),
                "worker_id_hash": worker_id_hash,
                "db_only_dispatch_verified": True,
                "remote_metadata_read_performed": False,
                "remote_content_read_performed": False,
                "document_mutated": False,
                "processing_enqueued": False,
                "ai_executed": False,
            },
        )
        db.commit()
        db.refresh(dispatch)
        return dispatch

    db.rollback()
    return None
