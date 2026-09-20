from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    ensure_due_tick_observation_integrity,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
    ExternalDocumentSourceObservationReviewHandoffReceipt,
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


def _normalize_projector_id(value: str) -> str:
    normalized = " ".join(value.strip().lower().split())
    if len(normalized) < 3 or len(normalized) > 128:
        raise ExternalDocumentSourceValidationError(
            "projector_id must contain between 3 and 128 characters"
        )
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_.:/")
    if any(ch not in allowed for ch in normalized):
        raise ExternalDocumentSourceValidationError(
            "projector_id contains unsupported characters"
        )
    return normalized


def _projector_hash(projector_id: str) -> str:
    normalized = _normalize_projector_id(projector_id)
    configured = _normalize_projector_id(
        get_settings().external_evidence_review_projector_id
    )
    if normalized != configured:
        raise ExternalDocumentSourceConflictError(
            "Internal review projector is not authorized"
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safety() -> dict[str, bool]:
    return {
        "observation_integrity_verified": True,
        "eligible_result_verified": True,
        "historical_snapshot_preserved": True,
        "projector_identity_verified": True,
        "human_user_impersonated": False,
        "provider_client_constructed": False,
        "token_acquired": False,
        "remote_list_performed": False,
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


def _scope_hash(
    *,
    observation: ExternalDocumentSourceDueTickObservationExecution,
    projector_id_hash: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(observation.organization_id),
            "claim_id": str(observation.claim_id),
            "profile_id": str(observation.profile_id),
            "observation_execution_id": str(observation.id),
            "observation_completion_hash": observation.completion_hash,
            "schedule_id": str(observation.schedule_id),
            "binding_id": str(observation.binding_id),
            "document_family_id": str(observation.document_family_id),
            "observed_document_id": str(observation.current_document_id),
            "observed_version_number": observation.current_version_number,
            "provider_kind": observation.provider_kind,
            "profile_hash": observation.profile_hash,
            "stable_source_item_hash": observation.stable_source_item_hash,
            "due_at": _iso(observation.due_at),
            "result_status": observation.result_status,
            "observed_projection_hash": observation.observed_projection_hash,
            "observed_version_token_hash": observation.observed_version_token_hash,
            "projector_id_hash": projector_id_hash,
        }
    )


def _completion_hash(
    handoff: ExternalDocumentSourceObservationReviewHandoff,
) -> str:
    return _canonical_hash(
        {
            "handoff_id": str(handoff.id),
            "scope_hash": handoff.scope_hash,
            "status": handoff.status,
            "projected_at": _iso(handoff.projected_at),
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceObservationReviewHandoffReceipt,
) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "handoff_id": str(receipt.handoff_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "projector_id_hash": receipt.projector_id_hash,
            "occurred_at": _iso(receipt.occurred_at),
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            **_safety(),
        }
    )


def ensure_observation_review_handoff_integrity(
    db: Session,
    handoff: ExternalDocumentSourceObservationReviewHandoff,
) -> None:
    observation = db.get(
        ExternalDocumentSourceDueTickObservationExecution,
        handoff.observation_execution_id,
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff source observation is missing"
        )
    ensure_due_tick_observation_integrity(db, observation)
    if observation.result_status not in {"changed", "missing"}:
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff source result is no longer eligible"
        )

    expected = {
        "organization_id": observation.organization_id,
        "claim_id": observation.claim_id,
        "profile_id": observation.profile_id,
        "schedule_id": observation.schedule_id,
        "binding_id": observation.binding_id,
        "document_family_id": observation.document_family_id,
        "observed_document_id": observation.current_document_id,
        "observed_version_number": observation.current_version_number,
        "provider_kind": observation.provider_kind,
        "profile_hash": observation.profile_hash,
        "stable_source_item_hash": observation.stable_source_item_hash,
        "observation_completion_hash": observation.completion_hash,
        "result_status": observation.result_status,
        "observed_projection_hash": observation.observed_projection_hash,
        "observed_version_token_hash": observation.observed_version_token_hash,
    }
    for field, value in expected.items():
        if getattr(handoff, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Observation review handoff snapshot drifted at {field}"
            )
    if _aware(handoff.due_at) != _aware(observation.due_at):
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff due tick drifted"
        )

    expected_scope = _scope_hash(
        observation=observation,
        projector_id_hash=handoff.projector_id_hash,
    )
    if (
        handoff.status != "pending"
        or handoff.scope_hash != expected_scope
        or handoff.completion_hash != _completion_hash(handoff)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(handoff, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation review handoff safety boundary drifted"
            )

    receipts = list(
        db.scalars(
            select(ExternalDocumentSourceObservationReviewHandoffReceipt).where(
                ExternalDocumentSourceObservationReviewHandoffReceipt.organization_id
                == handoff.organization_id,
                ExternalDocumentSourceObservationReviewHandoffReceipt.handoff_id
                == handoff.id,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "projected"
        or receipt.status_after != "pending"
        or receipt.projector_id_hash != handoff.projector_id_hash
        or _aware(receipt.occurred_at) != _aware(handoff.projected_at)
        or receipt.scope_hash != handoff.scope_hash
        or receipt.decision_hash != handoff.completion_hash
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation review handoff receipt safety boundary drifted"
            )


def project_observation_review_handoff(
    db: Session,
    *,
    observation_execution_id: UUID,
    projector_id: str,
    now: datetime | None = None,
) -> tuple[ExternalDocumentSourceObservationReviewHandoff | None, str]:
    projector_id_hash = _projector_hash(projector_id)
    observation = db.scalar(
        select(ExternalDocumentSourceDueTickObservationExecution)
        .where(
            ExternalDocumentSourceDueTickObservationExecution.id
            == observation_execution_id
        )
        .with_for_update()
    )
    if observation is None:
        raise ExternalDocumentSourceNotFoundError(
            "Due-tick observation execution not found"
        )
    ensure_due_tick_observation_integrity(db, observation)

    if observation.result_status == "unchanged":
        db.rollback()
        return None, "ineligible"
    if observation.result_status not in {"changed", "missing"}:
        db.rollback()
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation result is not eligible for review handoff"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceObservationReviewHandoff).where(
            ExternalDocumentSourceObservationReviewHandoff.observation_execution_id
            == observation.id
        )
    )
    if existing is not None:
        ensure_observation_review_handoff_integrity(db, existing)
        db.rollback()
        return existing, "replayed"

    projected_at = _aware(now or _utc_now())
    handoff = ExternalDocumentSourceObservationReviewHandoff(
        id=uuid4(),
        organization_id=observation.organization_id,
        claim_id=observation.claim_id,
        profile_id=observation.profile_id,
        observation_execution_id=observation.id,
        schedule_id=observation.schedule_id,
        binding_id=observation.binding_id,
        document_family_id=observation.document_family_id,
        observed_document_id=observation.current_document_id,
        observed_version_number=observation.current_version_number,
        provider_kind=observation.provider_kind,
        profile_hash=observation.profile_hash,
        stable_source_item_hash=observation.stable_source_item_hash,
        observation_completion_hash=observation.completion_hash,
        due_at=observation.due_at,
        result_status=observation.result_status,
        observed_projection_hash=observation.observed_projection_hash,
        observed_version_token_hash=observation.observed_version_token_hash,
        projector_id_hash=projector_id_hash,
        status="pending",
        projected_at=projected_at,
        scope_hash="",
        completion_hash="",
        **_safety(),
    )
    handoff.scope_hash = _scope_hash(
        observation=observation,
        projector_id_hash=projector_id_hash,
    )
    handoff.completion_hash = _completion_hash(handoff)
    db.add(handoff)
    db.flush()

    receipt = ExternalDocumentSourceObservationReviewHandoffReceipt(
        id=uuid4(),
        organization_id=observation.organization_id,
        handoff_id=handoff.id,
        sequence_number=1,
        event_type="projected",
        status_after="pending",
        projector_id_hash=projector_id_hash,
        occurred_at=projected_at,
        scope_hash=handoff.scope_hash,
        decision_hash=handoff.completion_hash,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    ensure_observation_review_handoff_integrity(db, handoff)

    write_audit_log(
        db,
        organization_id=observation.organization_id,
        user_id=None,
        action="PROJECT_EXTERNAL_EVIDENCE_OBSERVATION_REVIEW_HANDOFF",
        entity_type="external_document_source_observation_review_handoff",
        entity_id=handoff.id,
        new_values={
            "observation_execution_id": str(observation.id),
            "schedule_id": str(observation.schedule_id),
            "binding_id": str(observation.binding_id),
            "document_family_id": str(observation.document_family_id),
            "observed_document_id": str(observation.current_document_id),
            "observed_version_number": observation.current_version_number,
            "due_at": _iso(observation.due_at),
            "result_status": observation.result_status,
            "projector_id_hash": projector_id_hash,
            "status": "pending",
            "provider_client_constructed": False,
            "remote_metadata_read_performed": False,
            "remote_content_read_performed": False,
            "document_mutated": False,
            "evidence_admitted": False,
            "processing_enqueued": False,
            "ai_executed": False,
        },
    )
    db.commit()
    db.refresh(handoff)
    return handoff, "projected"


def project_next_observation_review_handoff(
    db: Session,
    *,
    projector_id: str,
    now: datetime | None = None,
    candidate_limit: int = 256,
) -> tuple[ExternalDocumentSourceObservationReviewHandoff, str] | None:
    if candidate_limit < 1 or candidate_limit > 1000:
        raise ValueError("candidate_limit must be between 1 and 1000")

    handoff_exists = exists(
        select(ExternalDocumentSourceObservationReviewHandoff.id).where(
            ExternalDocumentSourceObservationReviewHandoff.observation_execution_id
            == ExternalDocumentSourceDueTickObservationExecution.id
        )
    )
    candidate_ids = list(
        db.scalars(
            select(ExternalDocumentSourceDueTickObservationExecution.id)
            .where(
                ExternalDocumentSourceDueTickObservationExecution.result_status.in_(
                    ("changed", "missing")
                ),
                ~handoff_exists,
            )
            .order_by(
                ExternalDocumentSourceDueTickObservationExecution.completed_at,
                ExternalDocumentSourceDueTickObservationExecution.id,
            )
            .limit(candidate_limit)
        ).all()
    )
    for observation_execution_id in candidate_ids:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_execution_id,
            projector_id=projector_id,
            now=now,
        )
        if handoff is not None:
            return handoff, outcome
    db.rollback()
    return None
