from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
    ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    ensure_due_tick_dispatch_integrity,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    ensure_due_tick_observation_integrity,
    execute_due_tick_observation,
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


def _service_executor_hash(service_executor_id: str) -> str:
    normalized = " ".join(service_executor_id.strip().lower().split())
    if len(normalized) < 3 or len(normalized) > 128:
        raise ExternalDocumentSourceValidationError(
            "service_executor_id must contain between 3 and 128 characters"
        )
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_.:/")
    if any(ch not in allowed for ch in normalized):
        raise ExternalDocumentSourceValidationError(
            "service_executor_id contains unsupported characters"
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safety() -> dict[str, bool]:
    return {
        "dispatch_integrity_verified": True,
        "observation_integrity_verified": True,
        "service_executor_identity_verified": True,
        "metadata_observation_verified": True,
        "human_user_impersonated": False,
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
    }


def _scope_hash(
    *,
    dispatch: ExternalDocumentSourceDueTickDispatch,
    observation: ExternalDocumentSourceDueTickObservationExecution,
    service_executor_id_hash: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(dispatch.organization_id),
            "dispatch_id": str(dispatch.id),
            "dispatch_completion_hash": dispatch.completion_hash,
            "observation_execution_id": str(observation.id),
            "observation_completion_hash": observation.completion_hash,
            "schedule_id": str(dispatch.schedule_id),
            "binding_id": str(dispatch.binding_id),
            "document_family_id": str(dispatch.document_family_id),
            "current_document_id": str(dispatch.current_document_id),
            "current_version_number": dispatch.current_version_number,
            "due_at": _iso(dispatch.due_at),
            "service_executor_id_hash": service_executor_id_hash,
        }
    )


def _completion_hash(
    consumption: ExternalDocumentSourceDueTickDispatchConsumption,
) -> str:
    return _canonical_hash(
        {
            "consumption_id": str(consumption.id),
            "scope_hash": consumption.scope_hash,
            "status": consumption.status,
            "consumed_at": _iso(consumption.consumed_at),
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "consumption_id": str(receipt.consumption_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "service_executor_id_hash": receipt.service_executor_id_hash,
            "occurred_at": _iso(receipt.occurred_at),
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            **_safety(),
        }
    )


def _verify_dispatch_observation_match(
    dispatch: ExternalDocumentSourceDueTickDispatch,
    observation: ExternalDocumentSourceDueTickObservationExecution,
) -> None:
    if (
        observation.organization_id != dispatch.organization_id
        or observation.claim_id != dispatch.claim_id
        or observation.profile_id != dispatch.profile_id
        or observation.schedule_id != dispatch.schedule_id
        or observation.binding_id != dispatch.binding_id
        or observation.document_family_id != dispatch.document_family_id
        or observation.current_document_id != dispatch.current_document_id
        or observation.current_version_number != dispatch.current_version_number
        or observation.schedule_revision_number != dispatch.schedule_revision_number
        or observation.schedule_authorization_hash != dispatch.schedule_authorization_hash
        or observation.binding_completion_hash != dispatch.binding_completion_hash
        or observation.provider_kind != dispatch.provider_kind
        or observation.profile_hash != dispatch.profile_hash
        or observation.stable_source_item_hash != dispatch.stable_source_item_hash
        or observation.cadence_class != dispatch.cadence_class
        or observation.cadence_minutes != dispatch.cadence_minutes
        or _aware(observation.due_at) != _aware(dispatch.due_at)
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch does not match the completed observation authority"
        )


def ensure_due_tick_dispatch_consumption_integrity(
    db: Session,
    consumption: ExternalDocumentSourceDueTickDispatchConsumption,
) -> None:
    dispatch = db.get(ExternalDocumentSourceDueTickDispatch, consumption.dispatch_id)
    if dispatch is None:
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch consumption dispatch lineage is missing"
        )
    ensure_due_tick_dispatch_integrity(db, dispatch)

    observation = db.get(
        ExternalDocumentSourceDueTickObservationExecution,
        consumption.observation_execution_id,
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch consumption observation lineage is missing"
        )
    ensure_due_tick_observation_integrity(db, observation)
    _verify_dispatch_observation_match(dispatch, observation)

    if consumption.status == "executed":
        if (
            observation.actor_kind != "service"
            or observation.executed_by_id is not None
            or observation.service_executor_id_hash != consumption.service_executor_id_hash
        ):
            raise ExternalDocumentSourceConflictError(
                "Executed dispatch consumption service identity drifted"
            )
    elif consumption.status != "linked_existing":
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch consumption status drifted"
        )

    expected_scope = _scope_hash(
        dispatch=dispatch,
        observation=observation,
        service_executor_id_hash=consumption.service_executor_id_hash,
    )
    if (
        consumption.scope_hash != expected_scope
        or consumption.completion_hash != _completion_hash(consumption)
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch consumption cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(consumption, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Due-tick dispatch consumption safety boundary drifted"
            )

    receipts = list(
        db.scalars(
            select(ExternalDocumentSourceDueTickDispatchConsumptionReceipt).where(
                ExternalDocumentSourceDueTickDispatchConsumptionReceipt.organization_id
                == consumption.organization_id,
                ExternalDocumentSourceDueTickDispatchConsumptionReceipt.consumption_id
                == consumption.id,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch consumption receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "consumed"
        or receipt.status_after != consumption.status
        or receipt.service_executor_id_hash != consumption.service_executor_id_hash
        or _aware(receipt.occurred_at) != _aware(consumption.consumed_at)
        or receipt.scope_hash != consumption.scope_hash
        or receipt.decision_hash != consumption.completion_hash
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch consumption receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Due-tick dispatch consumption receipt safety boundary drifted"
            )


def _persist_consumption(
    db: Session,
    *,
    dispatch: ExternalDocumentSourceDueTickDispatch,
    observation: ExternalDocumentSourceDueTickObservationExecution,
    service_executor_id_hash: str,
    status: str,
    consumed_at: datetime,
) -> tuple[ExternalDocumentSourceDueTickDispatchConsumption, str]:
    existing = db.scalar(
        select(ExternalDocumentSourceDueTickDispatchConsumption).where(
            ExternalDocumentSourceDueTickDispatchConsumption.dispatch_id == dispatch.id
        )
    )
    if existing is not None:
        ensure_due_tick_dispatch_consumption_integrity(db, existing)
        if (
            existing.observation_execution_id != observation.id
            or existing.service_executor_id_hash != service_executor_id_hash
        ):
            raise ExternalDocumentSourceConflictError(
                "Due-tick dispatch was already consumed by different authority"
            )
        return existing, "replayed"

    consumption = ExternalDocumentSourceDueTickDispatchConsumption(
        id=uuid4(),
        organization_id=dispatch.organization_id,
        dispatch_id=dispatch.id,
        observation_execution_id=observation.id,
        service_executor_id_hash=service_executor_id_hash,
        status=status,
        consumed_at=consumed_at,
        scope_hash="",
        completion_hash="",
        **_safety(),
    )
    consumption.scope_hash = _scope_hash(
        dispatch=dispatch,
        observation=observation,
        service_executor_id_hash=service_executor_id_hash,
    )
    consumption.completion_hash = _completion_hash(consumption)
    db.add(consumption)
    db.flush()

    receipt = ExternalDocumentSourceDueTickDispatchConsumptionReceipt(
        id=uuid4(),
        organization_id=dispatch.organization_id,
        consumption_id=consumption.id,
        sequence_number=1,
        event_type="consumed",
        status_after=status,
        service_executor_id_hash=service_executor_id_hash,
        occurred_at=consumed_at,
        scope_hash=consumption.scope_hash,
        decision_hash=consumption.completion_hash,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    ensure_due_tick_dispatch_consumption_integrity(db, consumption)

    write_audit_log(
        db,
        organization_id=dispatch.organization_id,
        user_id=None,
        action="CONSUME_EXTERNAL_EVIDENCE_DUE_TICK_DISPATCH",
        entity_type="external_document_source_due_tick_dispatch_consumption",
        entity_id=consumption.id,
        new_values={
            "dispatch_id": str(dispatch.id),
            "observation_execution_id": str(observation.id),
            "schedule_id": str(dispatch.schedule_id),
            "binding_id": str(dispatch.binding_id),
            "document_family_id": str(dispatch.document_family_id),
            "current_document_id": str(dispatch.current_document_id),
            "current_version_number": dispatch.current_version_number,
            "due_at": _iso(dispatch.due_at),
            "service_executor_id_hash": service_executor_id_hash,
            "consumption_status": status,
            "human_user_impersonated": False,
            "remote_content_read_performed": False,
            "document_mutated": False,
            "processing_enqueued": False,
            "ai_executed": False,
        },
    )
    db.commit()
    db.refresh(consumption)
    return consumption, "consumed"


def consume_due_tick_dispatch(
    db: Session,
    *,
    dispatch_id: UUID,
    service_executor_id: str,
    now: datetime | None = None,
) -> tuple[
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickDispatchConsumption,
    str,
]:
    service_executor_id_hash = _service_executor_hash(service_executor_id)
    dispatch = db.scalar(
        select(ExternalDocumentSourceDueTickDispatch)
        .where(ExternalDocumentSourceDueTickDispatch.id == dispatch_id)
        .with_for_update()
    )
    if dispatch is None:
        raise ExternalDocumentSourceNotFoundError("Due-tick dispatch not found")
    ensure_due_tick_dispatch_integrity(db, dispatch)

    existing_consumption = db.scalar(
        select(ExternalDocumentSourceDueTickDispatchConsumption).where(
            ExternalDocumentSourceDueTickDispatchConsumption.dispatch_id == dispatch.id
        )
    )
    if existing_consumption is not None:
        ensure_due_tick_dispatch_consumption_integrity(db, existing_consumption)
        if existing_consumption.service_executor_id_hash != service_executor_id_hash:
            raise ExternalDocumentSourceConflictError(
                "Due-tick dispatch was already consumed by a different service executor"
            )
        observation = db.get(
            ExternalDocumentSourceDueTickObservationExecution,
            existing_consumption.observation_execution_id,
        )
        assert observation is not None
        return observation, existing_consumption, "replayed"

    existing_observation = db.scalar(
        select(ExternalDocumentSourceDueTickObservationExecution).where(
            ExternalDocumentSourceDueTickObservationExecution.organization_id
            == dispatch.organization_id,
            ExternalDocumentSourceDueTickObservationExecution.schedule_id
            == dispatch.schedule_id,
            ExternalDocumentSourceDueTickObservationExecution.due_at
            == dispatch.due_at,
        )
    )
    if existing_observation is not None:
        ensure_due_tick_observation_integrity(db, existing_observation)
        _verify_dispatch_observation_match(dispatch, existing_observation)
        consumption, _ = _persist_consumption(
            db,
            dispatch=dispatch,
            observation=existing_observation,
            service_executor_id_hash=service_executor_id_hash,
            status="linked_existing",
            consumed_at=_aware(now or _utc_now()),
        )
        return existing_observation, consumption, "linked_existing"

    try:
        observation, execution_outcome = execute_due_tick_observation(
            db,
            organization_id=dispatch.organization_id,
            profile_id=dispatch.profile_id,
            schedule_id=dispatch.schedule_id,
            executed_by_id=None,
            service_executor_id_hash=service_executor_id_hash,
            expected_due_at=dispatch.due_at,
            expected_dispatch=dispatch,
            request_key=f"ae-dispatch-{dispatch.id}",
            reason=(
                "Consume one immutable scheduler dispatch through the explicit "
                "internal service-executor metadata-only observation boundary."
            ),
            now=now,
        )
    except ExternalDocumentSourceConflictError:
        db.rollback()
        observation = db.scalar(
            select(ExternalDocumentSourceDueTickObservationExecution).where(
                ExternalDocumentSourceDueTickObservationExecution.organization_id
                == dispatch.organization_id,
                ExternalDocumentSourceDueTickObservationExecution.schedule_id
                == dispatch.schedule_id,
                ExternalDocumentSourceDueTickObservationExecution.due_at
                == dispatch.due_at,
            )
        )
        if observation is None:
            raise
        ensure_due_tick_observation_integrity(db, observation)
        _verify_dispatch_observation_match(dispatch, observation)
        status = "linked_existing"
    else:
        status = (
            "executed"
            if observation.actor_kind == "service"
            and observation.service_executor_id_hash == service_executor_id_hash
            else "linked_existing"
        )
        if execution_outcome not in {"completed", "replayed"}:
            raise ExternalDocumentSourceConflictError(
                "Unexpected service due-tick observation outcome"
            )

    dispatch = db.get(ExternalDocumentSourceDueTickDispatch, dispatch_id)
    if dispatch is None:
        raise ExternalDocumentSourceConflictError(
            "Due-tick dispatch disappeared before consumption receipt"
        )
    ensure_due_tick_dispatch_integrity(db, dispatch)
    consumption, consumption_outcome = _persist_consumption(
        db,
        dispatch=dispatch,
        observation=observation,
        service_executor_id_hash=service_executor_id_hash,
        status=status,
        consumed_at=_aware(now or _utc_now()),
    )
    return observation, consumption, consumption_outcome


def consume_next_due_tick_dispatch(
    db: Session,
    *,
    service_executor_id: str,
    now: datetime | None = None,
    candidate_limit: int = 256,
) -> tuple[
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickDispatchConsumption,
    str,
] | None:
    if candidate_limit < 1 or candidate_limit > 1000:
        raise ValueError("candidate_limit must be between 1 and 1000")

    consumed_exists = exists(
        select(ExternalDocumentSourceDueTickDispatchConsumption.id).where(
            ExternalDocumentSourceDueTickDispatchConsumption.dispatch_id
            == ExternalDocumentSourceDueTickDispatch.id
        )
    )
    candidate_ids = list(
        db.scalars(
            select(ExternalDocumentSourceDueTickDispatch.id)
            .where(~consumed_exists)
            .order_by(
                ExternalDocumentSourceDueTickDispatch.due_at,
                ExternalDocumentSourceDueTickDispatch.dispatched_at,
                ExternalDocumentSourceDueTickDispatch.id,
            )
            .limit(candidate_limit)
        ).all()
    )
    for dispatch_id in candidate_ids:
        try:
            return consume_due_tick_dispatch(
                db,
                dispatch_id=dispatch_id,
                service_executor_id=service_executor_id,
                now=now,
            )
        except ExternalDocumentSourceConflictError:
            # A stale/disabled/replaced/tampered dispatch remains unconsumed and
            # fail-closed, but must not prevent later independent dispatches
            # from being considered by the bounded worker.
            db.rollback()
            continue
    db.rollback()
    return None
