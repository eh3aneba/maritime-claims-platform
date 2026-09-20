from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
    ExternalDocumentSourceRecurringObservationScheduleReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)

CADENCE_MINUTES = {
    "hourly": 60,
    "every_6_hours": 360,
    "every_12_hours": 720,
    "daily": 1440,
}


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


def _cadence_minutes(cadence_class: str) -> int:
    minutes = CADENCE_MINUTES.get(cadence_class)
    if minutes is None:
        raise ExternalDocumentSourceValidationError(
            "Unsupported recurring observation cadence"
        )
    return minutes


def _safety() -> dict[str, bool]:
    return {
        "family_binding_verified": True,
        "stable_source_identity_verified": True,
        "human_authorization_recorded": True,
        "bounded_cadence_verified": True,
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
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_worker_started": False,
    }


def _binding_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> ExternalDocumentSourceEvidenceFamilyBinding:
    binding = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding)
        .where(
            ExternalDocumentSourceEvidenceFamilyBinding.id == binding_id,
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id == profile_id,
        )
        .with_for_update()
    )
    if binding is None:
        raise ExternalDocumentSourceNotFoundError(
            "External Evidence family binding not found"
        )
    _ensure_binding_integrity(db, binding)

    current_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.organization_id == organization_id,
            Document.claim_id == binding.claim_id,
            Document.document_family_id == binding.document_family_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
        )
    )
    if current_count != 1:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation requires exactly one canonical current Document"
        )
    return binding


def _scope_hash(
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    *,
    prior_schedule_id: UUID | None,
    revision_number: int,
    cadence_class: str,
    cadence_minutes: int,
    effective_at: datetime,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(binding.organization_id),
            "claim_id": str(binding.claim_id),
            "profile_id": str(binding.profile_id),
            "binding_id": str(binding.id),
            "binding_completion_hash": binding.completion_hash,
            "document_family_id": str(binding.document_family_id),
            "provider_kind": binding.provider_kind,
            "profile_hash": binding.profile_hash,
            "stable_source_item_hash": binding.stable_source_item_hash,
            "prior_schedule_id": str(prior_schedule_id) if prior_schedule_id else None,
            "revision_number": revision_number,
            "cadence_class": cadence_class,
            "cadence_minutes": cadence_minutes,
            "effective_at": _iso(effective_at),
            "request_key": request_key,
        }
    )


def _request_hash(schedule: ExternalDocumentSourceRecurringObservationSchedule) -> str:
    return _canonical_hash(
        {
            "schedule_id": str(schedule.id),
            "scope_hash": schedule.scope_hash,
            "authorized_by_id": str(schedule.authorized_by_id),
            "authorization_reason": schedule.authorization_reason,
            "authorized_at": _iso(schedule.authorized_at),
            **_safety(),
        }
    )


def _authorization_hash(
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> str:
    return _canonical_hash(
        {
            "schedule_id": str(schedule.id),
            "scope_hash": schedule.scope_hash,
            "request_hash": schedule.request_hash,
            "status": "active",
            "revision_number": schedule.revision_number,
            "cadence_class": schedule.cadence_class,
            "cadence_minutes": schedule.cadence_minutes,
            "effective_at": _iso(schedule.effective_at),
            "next_due_at": _iso(schedule.next_due_at),
            **_safety(),
        }
    )


def _terminal_hash(
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> str:
    return _canonical_hash(
        {
            "schedule_id": str(schedule.id),
            "authorization_hash": schedule.authorization_hash,
            "status": "disabled",
            "disable_request_key": schedule.disable_request_key,
            "disabled_by_id": str(schedule.disabled_by_id),
            "disable_reason": schedule.disable_reason,
            "disabled_at": _iso(schedule.disabled_at),
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceRecurringObservationScheduleReceipt,
) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "schedule_id": str(receipt.schedule_id),
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
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> list[ExternalDocumentSourceRecurringObservationScheduleReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceRecurringObservationScheduleReceipt)
            .where(
                ExternalDocumentSourceRecurringObservationScheduleReceipt.organization_id
                == schedule.organization_id,
                ExternalDocumentSourceRecurringObservationScheduleReceipt.schedule_id
                == schedule.id,
            )
            .order_by(
                ExternalDocumentSourceRecurringObservationScheduleReceipt.sequence_number.asc()
            )
        ).all()
    )


def ensure_recurring_observation_schedule_integrity(
    db: Session,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
) -> None:
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
            "Recurring observation schedule family binding is missing"
        )
    _ensure_binding_integrity(db, binding)

    expected = {
        "claim_id": binding.claim_id,
        "document_family_id": binding.document_family_id,
        "provider_kind": binding.provider_kind,
        "profile_hash": binding.profile_hash,
        "stable_source_item_hash": binding.stable_source_item_hash,
        "binding_completion_hash": binding.completion_hash,
        "cadence_minutes": _cadence_minutes(schedule.cadence_class),
    }
    for field, value in expected.items():
        if getattr(schedule, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Recurring observation schedule integrity drifted at {field}"
            )

    if schedule.revision_number == 1:
        if schedule.prior_schedule_id is not None:
            raise ExternalDocumentSourceConflictError(
                "Recurring observation first revision lineage drifted"
            )
    else:
        prior = db.scalar(
            select(ExternalDocumentSourceRecurringObservationSchedule).where(
                ExternalDocumentSourceRecurringObservationSchedule.id
                == schedule.prior_schedule_id,
                ExternalDocumentSourceRecurringObservationSchedule.organization_id
                == schedule.organization_id,
                ExternalDocumentSourceRecurringObservationSchedule.binding_id
                == schedule.binding_id,
            )
        )
        if (
            prior is None
            or prior.revision_number + 1 != schedule.revision_number
            or prior.status != "disabled"
        ):
            raise ExternalDocumentSourceConflictError(
                "Recurring observation schedule revision lineage drifted"
            )
        ensure_recurring_observation_schedule_integrity(db, prior)

    expected_scope = _scope_hash(
        binding,
        prior_schedule_id=schedule.prior_schedule_id,
        revision_number=schedule.revision_number,
        cadence_class=schedule.cadence_class,
        cadence_minutes=schedule.cadence_minutes,
        effective_at=schedule.effective_at,
        request_key=schedule.request_key,
    )
    if (
        schedule.scope_hash != expected_scope
        or schedule.request_hash != _request_hash(schedule)
        or schedule.authorization_hash != _authorization_hash(schedule)
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(schedule, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Recurring observation schedule safety boundary drifted"
            )

    receipts = _receipts(db, schedule)
    expected_count = 1 if schedule.status == "active" else 2
    if len(receipts) != expected_count:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule receipt lifecycle drifted"
        )
    first = receipts[0]
    if (
        first.sequence_number != 1
        or first.event_type != "authorized"
        or first.status_after != "active"
        or first.actor_id != schedule.authorized_by_id
        or _aware(first.occurred_at) != _aware(schedule.authorized_at)
        or first.reason != schedule.authorization_reason
        or first.scope_hash != schedule.scope_hash
        or first.decision_hash != schedule.authorization_hash
        or first.prior_receipt_hash is not None
        or first.receipt_hash != _receipt_hash(first)
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule authorization receipt drifted"
        )

    if schedule.status == "active":
        if (
            schedule.active_binding_guard != schedule.binding_id
            or any(
                value is not None
                for value in (
                    schedule.disable_request_key,
                    schedule.disabled_by_id,
                    schedule.disable_reason,
                    schedule.disabled_at,
                    schedule.terminal_hash,
                )
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "Recurring observation active lifecycle drifted"
            )
        return

    if (
        schedule.status != "disabled"
        or schedule.active_binding_guard is not None
        or schedule.terminal_hash != _terminal_hash(schedule)
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation terminal lifecycle drifted"
        )
    second = receipts[1]
    if (
        second.sequence_number != 2
        or second.event_type != "disabled"
        or second.status_after != "disabled"
        or second.actor_id != schedule.disabled_by_id
        or _aware(second.occurred_at) != _aware(schedule.disabled_at)
        or second.reason != schedule.disable_reason
        or second.scope_hash != schedule.scope_hash
        or second.decision_hash != schedule.terminal_hash
        or second.prior_receipt_hash != first.receipt_hash
        or second.receipt_hash != _receipt_hash(second)
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule disable receipt drifted"
        )


def _new_schedule(
    db: Session,
    *,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    prior_schedule: ExternalDocumentSourceRecurringObservationSchedule | None,
    authorized_by_id: UUID,
    request_key: str,
    reason: str,
    cadence_class: str,
    effective_at: datetime | None,
) -> ExternalDocumentSourceRecurringObservationSchedule:
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        reason, field="reason", minimum=20, maximum=2000
    )
    cadence_minutes = _cadence_minutes(cadence_class)
    authorized_at = _utc_now()
    effective = _aware(effective_at) if effective_at is not None else authorized_at
    revision_number = 1 if prior_schedule is None else prior_schedule.revision_number + 1

    schedule = ExternalDocumentSourceRecurringObservationSchedule(
        id=uuid4(),
        organization_id=binding.organization_id,
        claim_id=binding.claim_id,
        profile_id=binding.profile_id,
        binding_id=binding.id,
        document_family_id=binding.document_family_id,
        prior_schedule_id=prior_schedule.id if prior_schedule else None,
        revision_number=revision_number,
        provider_kind=binding.provider_kind,
        profile_hash=binding.profile_hash,
        stable_source_item_hash=binding.stable_source_item_hash,
        binding_completion_hash=binding.completion_hash,
        cadence_class=cadence_class,
        cadence_minutes=cadence_minutes,
        effective_at=effective,
        next_due_at=effective,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="active",
        active_binding_guard=binding.id,
        authorized_by_id=authorized_by_id,
        authorization_reason=normalized_reason,
        authorized_at=authorized_at,
        authorization_hash="",
        **_safety(),
    )
    schedule.scope_hash = _scope_hash(
        binding,
        prior_schedule_id=schedule.prior_schedule_id,
        revision_number=schedule.revision_number,
        cadence_class=schedule.cadence_class,
        cadence_minutes=schedule.cadence_minutes,
        effective_at=schedule.effective_at,
        request_key=schedule.request_key,
    )
    schedule.request_hash = _request_hash(schedule)
    schedule.authorization_hash = _authorization_hash(schedule)
    db.add(schedule)
    db.flush()

    receipt = ExternalDocumentSourceRecurringObservationScheduleReceipt(
        id=uuid4(),
        organization_id=binding.organization_id,
        schedule_id=schedule.id,
        sequence_number=1,
        event_type="authorized",
        status_after="active",
        actor_id=authorized_by_id,
        occurred_at=authorized_at,
        reason=normalized_reason,
        scope_hash=schedule.scope_hash,
        decision_hash=schedule.authorization_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    return schedule


def _disable_schedule(
    db: Session,
    *,
    schedule: ExternalDocumentSourceRecurringObservationSchedule,
    disabled_by_id: UUID,
    request_key: str,
    reason: str,
) -> None:
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        reason, field="reason", minimum=20, maximum=2000
    )
    if schedule.status != "active":
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule is already disabled"
        )
    receipts = _receipts(db, schedule)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule cannot be disabled with invalid receipt lineage"
        )
    disabled_at = _utc_now()
    schedule.status = "disabled"
    schedule.active_binding_guard = None
    schedule.disable_request_key = normalized_key
    schedule.disabled_by_id = disabled_by_id
    schedule.disable_reason = normalized_reason
    schedule.disabled_at = disabled_at
    schedule.terminal_hash = _terminal_hash(schedule)
    db.flush()

    receipt = ExternalDocumentSourceRecurringObservationScheduleReceipt(
        id=uuid4(),
        organization_id=schedule.organization_id,
        schedule_id=schedule.id,
        sequence_number=2,
        event_type="disabled",
        status_after="disabled",
        actor_id=disabled_by_id,
        occurred_at=disabled_at,
        reason=normalized_reason,
        scope_hash=schedule.scope_hash,
        decision_hash=schedule.terminal_hash,
        prior_receipt_hash=receipts[0].receipt_hash,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def authorize_recurring_observation_schedule(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    authorized_by_id: UUID,
    request_key: str,
    reason: str,
    cadence_class: str,
    effective_at: datetime | None,
) -> tuple[ExternalDocumentSourceRecurringObservationSchedule, str]:
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        reason, field="reason", minimum=20, maximum=2000
    )
    cadence_minutes = _cadence_minutes(cadence_class)
    normalized_effective = _aware(effective_at) if effective_at is not None else None

    existing_request = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_recurring_observation_schedule_integrity(db, existing_request)
        if (
            existing_request.binding_id != binding_id
            or existing_request.authorized_by_id != authorized_by_id
            or existing_request.authorization_reason != normalized_reason
            or existing_request.cadence_class != cadence_class
            or existing_request.cadence_minutes != cadence_minutes
            or (
                normalized_effective is not None
                and _aware(existing_request.effective_at) != normalized_effective
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "Recurring observation request key was already used with different inputs"
            )
        return existing_request, "replayed"

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    active = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule)
        .where(
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.binding_id
            == binding_id,
            ExternalDocumentSourceRecurringObservationSchedule.status == "active",
        )
        .with_for_update()
    )
    if active is not None:
        ensure_recurring_observation_schedule_integrity(db, active)
        raise ExternalDocumentSourceConflictError(
            "An active recurring observation schedule already exists for this Evidence family"
        )

    prior = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule)
        .where(
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.binding_id
            == binding_id,
        )
        .order_by(
            ExternalDocumentSourceRecurringObservationSchedule.revision_number.desc()
        )
        .limit(1)
    )
    schedule = _new_schedule(
        db,
        binding=binding,
        prior_schedule=prior,
        authorized_by_id=authorized_by_id,
        request_key=normalized_key,
        reason=normalized_reason,
        cadence_class=cadence_class,
        effective_at=normalized_effective,
    )
    ensure_recurring_observation_schedule_integrity(db, schedule)
    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=authorized_by_id,
        action="AUTHORIZE_EXTERNAL_EVIDENCE_RECURRING_OBSERVATION",
        entity_type="external_document_source_recurring_observation_schedule",
        entity_id=schedule.id,
        new_values={
            "claim_id": str(schedule.claim_id),
            "binding_id": str(schedule.binding_id),
            "document_family_id": str(schedule.document_family_id),
            "revision_number": schedule.revision_number,
            "cadence_class": schedule.cadence_class,
            "effective_at": _iso(schedule.effective_at),
            "next_due_at": _iso(schedule.next_due_at),
            "provider_io_performed": False,
            "background_worker_started": False,
        },
    )
    db.commit()
    db.refresh(schedule)
    return schedule, "authorized"


def replace_recurring_observation_schedule(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    schedule_id: UUID,
    actor_id: UUID,
    request_key: str,
    reason: str,
    cadence_class: str,
    effective_at: datetime | None,
) -> tuple[ExternalDocumentSourceRecurringObservationSchedule, str]:
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        reason, field="reason", minimum=20, maximum=2000
    )
    cadence_minutes = _cadence_minutes(cadence_class)
    normalized_effective = _aware(effective_at) if effective_at is not None else None

    existing_request = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_recurring_observation_schedule_integrity(db, existing_request)
        if (
            existing_request.prior_schedule_id != schedule_id
            or existing_request.authorized_by_id != actor_id
            or existing_request.authorization_reason != normalized_reason
            or existing_request.cadence_class != cadence_class
            or existing_request.cadence_minutes != cadence_minutes
            or (
                normalized_effective is not None
                and _aware(existing_request.effective_at) != normalized_effective
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "Recurring observation replacement request key was already used with different inputs"
            )
        return existing_request, "replayed"

    snapshot = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
        )
    )
    if snapshot is None:
        raise ExternalDocumentSourceNotFoundError(
            "Recurring observation schedule not found"
        )
    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=snapshot.binding_id,
    )
    current = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule)
        .where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.binding_id
            == binding.id,
        )
        .with_for_update()
    )
    if current is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule changed while acquiring family authority"
        )
    ensure_recurring_observation_schedule_integrity(db, current)
    if current.status != "active":
        raise ExternalDocumentSourceConflictError(
            "Only an active recurring observation schedule can be replaced"
        )
    _disable_schedule(
        db,
        schedule=current,
        disabled_by_id=actor_id,
        request_key=normalized_key,
        reason=normalized_reason,
    )
    replacement = _new_schedule(
        db,
        binding=binding,
        prior_schedule=current,
        authorized_by_id=actor_id,
        request_key=normalized_key,
        reason=normalized_reason,
        cadence_class=cadence_class,
        effective_at=normalized_effective,
    )
    ensure_recurring_observation_schedule_integrity(db, current)
    ensure_recurring_observation_schedule_integrity(db, replacement)
    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="REPLACE_EXTERNAL_EVIDENCE_RECURRING_OBSERVATION",
        entity_type="external_document_source_recurring_observation_schedule",
        entity_id=replacement.id,
        new_values={
            "binding_id": str(replacement.binding_id),
            "prior_schedule_id": str(current.id),
            "revision_number": replacement.revision_number,
            "cadence_class": replacement.cadence_class,
            "provider_io_performed": False,
            "background_worker_started": False,
        },
    )
    db.commit()
    db.refresh(replacement)
    return replacement, "replaced"


def disable_recurring_observation_schedule(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    schedule_id: UUID,
    actor_id: UUID,
    request_key: str,
    reason: str,
) -> tuple[ExternalDocumentSourceRecurringObservationSchedule, str]:
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        reason, field="reason", minimum=20, maximum=2000
    )
    existing_request = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.disable_request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_recurring_observation_schedule_integrity(db, existing_request)
        if (
            existing_request.id != schedule_id
            or existing_request.disabled_by_id != actor_id
            or existing_request.disable_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Recurring observation disable request key was already used with different inputs"
            )
        return existing_request, "replayed"

    snapshot = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
        )
    )
    if snapshot is None:
        raise ExternalDocumentSourceNotFoundError(
            "Recurring observation schedule not found"
        )
    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=snapshot.binding_id,
    )
    schedule = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule)
        .where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.binding_id
            == binding.id,
        )
        .with_for_update()
    )
    if schedule is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation schedule changed while acquiring family authority"
        )
    ensure_recurring_observation_schedule_integrity(db, schedule)
    _disable_schedule(
        db,
        schedule=schedule,
        disabled_by_id=actor_id,
        request_key=normalized_key,
        reason=normalized_reason,
    )
    ensure_recurring_observation_schedule_integrity(db, schedule)
    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="DISABLE_EXTERNAL_EVIDENCE_RECURRING_OBSERVATION",
        entity_type="external_document_source_recurring_observation_schedule",
        entity_id=schedule.id,
        new_values={
            "binding_id": str(schedule.binding_id),
            "revision_number": schedule.revision_number,
            "status": "disabled",
            "provider_io_performed": False,
            "background_worker_started": False,
        },
    )
    db.commit()
    db.refresh(schedule)
    return schedule, "disabled"


def get_recurring_observation_schedule(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    schedule_id: UUID,
) -> ExternalDocumentSourceRecurringObservationSchedule:
    schedule = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.id == schedule_id,
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
        )
    )
    if schedule is None:
        raise ExternalDocumentSourceNotFoundError(
            "Recurring observation schedule not found"
        )
    ensure_recurring_observation_schedule_integrity(db, schedule)
    return schedule


def get_active_recurring_observation_schedule(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> ExternalDocumentSourceRecurringObservationSchedule | None:
    _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    schedule = db.scalar(
        select(ExternalDocumentSourceRecurringObservationSchedule).where(
            ExternalDocumentSourceRecurringObservationSchedule.organization_id
            == organization_id,
            ExternalDocumentSourceRecurringObservationSchedule.profile_id
            == profile_id,
            ExternalDocumentSourceRecurringObservationSchedule.binding_id
            == binding_id,
            ExternalDocumentSourceRecurringObservationSchedule.status == "active",
        )
    )
    if schedule is not None:
        ensure_recurring_observation_schedule_integrity(db, schedule)
    return schedule


def list_recurring_observation_schedule_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    schedule_id: UUID,
) -> list[ExternalDocumentSourceRecurringObservationScheduleReceipt]:
    schedule = get_recurring_observation_schedule(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        schedule_id=schedule_id,
    )
    return _receipts(db, schedule)
