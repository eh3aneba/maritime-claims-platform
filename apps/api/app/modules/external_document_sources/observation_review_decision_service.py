from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document
from app.modules.external_document_sources.family_version_admission_service import (
    _binding_for_update,
    _lock_current_family_document,
    _prior_source_state,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationReviewDecisionReceipt,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    ensure_observation_review_handoff_integrity,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
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


def _normalize_text(
    value: str,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    return normalized


def _safety() -> dict[str, bool]:
    return {
        "handoff_integrity_verified": True,
        "current_authority_verified": True,
        "current_document_verified": True,
        "human_decision_recorded": True,
        "service_identity_used_as_human": False,
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


def _status_for_decision(decision_kind: str) -> str:
    mapping = {
        "approve_refresh": "refresh_authorized",
        "dismiss": "dismissed",
        "acknowledge_missing": "missing_acknowledged",
    }
    try:
        return mapping[decision_kind]
    except KeyError:
        raise ExternalDocumentSourceValidationError(
            "decision_kind must be approve_refresh, dismiss, or acknowledge_missing"
        ) from None


def _validate_matrix(*, result_status: str, decision_kind: str) -> None:
    allowed = {
        "changed": {"approve_refresh", "dismiss"},
        "missing": {"acknowledge_missing", "dismiss"},
    }
    if result_status not in allowed or decision_kind not in allowed[result_status]:
        raise ExternalDocumentSourceConflictError(
            f"Decision {decision_kind} is not allowed for {result_status} handoff"
        )


def _scope_hash(
    *,
    handoff: ExternalDocumentSourceObservationReviewHandoff,
    current: Document,
    binding_completion_hash: str,
    prior_projection_hash: str,
    prior_provider_version_hash: str | None,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(handoff.organization_id),
            "claim_id": str(handoff.claim_id),
            "profile_id": str(handoff.profile_id),
            "handoff_id": str(handoff.id),
            "handoff_completion_hash": handoff.completion_hash,
            "observation_execution_id": str(handoff.observation_execution_id),
            "schedule_id": str(handoff.schedule_id),
            "binding_id": str(handoff.binding_id),
            "binding_completion_hash": binding_completion_hash,
            "document_family_id": str(handoff.document_family_id),
            "current_document_id": str(current.id),
            "current_version_number": current.version_number,
            "current_document_file_hash": current.file_hash,
            "provider_kind": handoff.provider_kind,
            "profile_hash": handoff.profile_hash,
            "stable_source_item_hash": handoff.stable_source_item_hash,
            "result_status": handoff.result_status,
            "prior_projection_hash": prior_projection_hash,
            "prior_provider_version_hash": prior_provider_version_hash,
            "observed_projection_hash": handoff.observed_projection_hash,
            "observed_version_token_hash": handoff.observed_version_token_hash,
            "request_key": request_key,
        }
    )


def _request_hash(
    decision: ExternalDocumentSourceObservationReviewDecision,
) -> str:
    return _canonical_hash(
        {
            "decision_id": str(decision.id),
            "scope_hash": decision.scope_hash,
            "request_key": decision.request_key,
            "decision_kind": decision.decision_kind,
            "decided_by_id": str(decision.decided_by_id),
            "decision_reason": decision.decision_reason,
            "decided_at": _iso(decision.decided_at),
            **_safety(),
        }
    )


def _completion_hash(
    decision: ExternalDocumentSourceObservationReviewDecision,
) -> str:
    return _canonical_hash(
        {
            "decision_id": str(decision.id),
            "scope_hash": decision.scope_hash,
            "request_hash": decision.request_hash,
            "status": decision.status,
            "decision_kind": decision.decision_kind,
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceObservationReviewDecisionReceipt,
) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "decision_id": str(receipt.decision_id),
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


def _authorization_scope_hash(
    authorization: ExternalDocumentSourceObservationRefreshAuthorization,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(authorization.organization_id),
            "claim_id": str(authorization.claim_id),
            "profile_id": str(authorization.profile_id),
            "handoff_id": str(authorization.handoff_id),
            "decision_id": str(authorization.decision_id),
            "binding_id": str(authorization.binding_id),
            "document_family_id": str(authorization.document_family_id),
            "current_document_id": str(authorization.current_document_id),
            "current_version_number": authorization.current_version_number,
            "current_document_file_hash": authorization.current_document_file_hash,
            "provider_kind": authorization.provider_kind,
            "profile_hash": authorization.profile_hash,
            "stable_source_item_hash": authorization.stable_source_item_hash,
            "handoff_completion_hash": authorization.handoff_completion_hash,
            "decision_completion_hash": authorization.decision_completion_hash,
            "binding_completion_hash": authorization.binding_completion_hash,
            "result_status": authorization.result_status,
            "prior_projection_hash": authorization.prior_projection_hash,
            "prior_provider_version_hash": authorization.prior_provider_version_hash,
            "observed_projection_hash": authorization.observed_projection_hash,
            "observed_version_token_hash": authorization.observed_version_token_hash,
            "execution_limit": authorization.execution_limit,
            "authorized_by_id": str(authorization.authorized_by_id),
            "authorized_at": _iso(authorization.authorized_at),
        }
    )


def _authorization_hash(
    authorization: ExternalDocumentSourceObservationRefreshAuthorization,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "status": authorization.status,
            **_safety(),
        }
    )


def _decision_receipts(
    db: Session,
    decision: ExternalDocumentSourceObservationReviewDecision,
) -> list[ExternalDocumentSourceObservationReviewDecisionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceObservationReviewDecisionReceipt).where(
                ExternalDocumentSourceObservationReviewDecisionReceipt.organization_id
                == decision.organization_id,
                ExternalDocumentSourceObservationReviewDecisionReceipt.decision_id
                == decision.id,
            )
        ).all()
    )


def _ensure_decision_core_integrity(
    db: Session,
    decision: ExternalDocumentSourceObservationReviewDecision,
) -> None:
    handoff = db.get(
        ExternalDocumentSourceObservationReviewHandoff,
        decision.handoff_id,
    )
    if handoff is None:
        raise ExternalDocumentSourceConflictError(
            "Observation review decision handoff is missing"
        )
    ensure_observation_review_handoff_integrity(db, handoff)

    historical_document = db.get(Document, decision.current_document_id)
    if historical_document is None:
        raise ExternalDocumentSourceConflictError(
            "Observation review decision historical Document is missing"
        )

    expected = {
        "organization_id": handoff.organization_id,
        "claim_id": handoff.claim_id,
        "profile_id": handoff.profile_id,
        "observation_execution_id": handoff.observation_execution_id,
        "schedule_id": handoff.schedule_id,
        "binding_id": handoff.binding_id,
        "document_family_id": handoff.document_family_id,
        "result_status": handoff.result_status,
        "provider_kind": handoff.provider_kind,
        "profile_hash": handoff.profile_hash,
        "stable_source_item_hash": handoff.stable_source_item_hash,
        "handoff_completion_hash": handoff.completion_hash,
        "observed_projection_hash": handoff.observed_projection_hash,
        "observed_version_token_hash": handoff.observed_version_token_hash,
    }
    for field, value in expected.items():
        if getattr(decision, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Observation review decision snapshot drifted at {field}"
            )

    if (
        historical_document.organization_id != decision.organization_id
        or historical_document.claim_id != decision.claim_id
        or historical_document.document_family_id != decision.document_family_id
        or historical_document.version_number != decision.current_version_number
        or historical_document.file_hash != decision.current_document_file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review decision historical Document snapshot drifted"
        )

    _validate_matrix(
        result_status=decision.result_status,
        decision_kind=decision.decision_kind,
    )
    if decision.status != _status_for_decision(decision.decision_kind):
        raise ExternalDocumentSourceConflictError(
            "Observation review decision lifecycle drifted"
        )
    expected_scope = _canonical_hash(
        {
            "organization_id": str(decision.organization_id),
            "claim_id": str(decision.claim_id),
            "profile_id": str(decision.profile_id),
            "handoff_id": str(decision.handoff_id),
            "handoff_completion_hash": decision.handoff_completion_hash,
            "observation_execution_id": str(decision.observation_execution_id),
            "schedule_id": str(decision.schedule_id),
            "binding_id": str(decision.binding_id),
            "binding_completion_hash": decision.binding_completion_hash,
            "document_family_id": str(decision.document_family_id),
            "current_document_id": str(decision.current_document_id),
            "current_version_number": decision.current_version_number,
            "current_document_file_hash": decision.current_document_file_hash,
            "provider_kind": decision.provider_kind,
            "profile_hash": decision.profile_hash,
            "stable_source_item_hash": decision.stable_source_item_hash,
            "result_status": decision.result_status,
            "prior_projection_hash": decision.prior_projection_hash,
            "prior_provider_version_hash": decision.prior_provider_version_hash,
            "observed_projection_hash": decision.observed_projection_hash,
            "observed_version_token_hash": decision.observed_version_token_hash,
            "request_key": decision.request_key,
        }
    )
    if (
        decision.scope_hash != expected_scope
        or decision.request_hash != _request_hash(decision)
        or decision.completion_hash != _completion_hash(decision)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review decision cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(decision, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation review decision safety boundary drifted"
            )

    receipts = _decision_receipts(db, decision)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Observation review decision receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != decision.decision_kind
        or receipt.status_after != decision.status
        or receipt.actor_id != decision.decided_by_id
        or _aware(receipt.occurred_at) != _aware(decision.decided_at)
        or receipt.reason != decision.decision_reason
        or receipt.scope_hash != decision.scope_hash
        or receipt.decision_hash != decision.completion_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review decision receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation review decision receipt safety boundary drifted"
            )


def ensure_observation_refresh_authorization_integrity(
    db: Session,
    authorization: ExternalDocumentSourceObservationRefreshAuthorization,
) -> None:
    decision = db.get(
        ExternalDocumentSourceObservationReviewDecision,
        authorization.decision_id,
    )
    if decision is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh authorization decision is missing"
        )
    _ensure_decision_core_integrity(db, decision)
    if decision.decision_kind != "approve_refresh" or decision.result_status != "changed":
        raise ExternalDocumentSourceConflictError(
            "Observation refresh authorization lacks an approved changed decision"
        )

    expected = {
        "organization_id": decision.organization_id,
        "claim_id": decision.claim_id,
        "profile_id": decision.profile_id,
        "handoff_id": decision.handoff_id,
        "binding_id": decision.binding_id,
        "document_family_id": decision.document_family_id,
        "current_document_id": decision.current_document_id,
        "current_version_number": decision.current_version_number,
        "current_document_file_hash": decision.current_document_file_hash,
        "provider_kind": decision.provider_kind,
        "profile_hash": decision.profile_hash,
        "stable_source_item_hash": decision.stable_source_item_hash,
        "handoff_completion_hash": decision.handoff_completion_hash,
        "decision_completion_hash": decision.completion_hash,
        "binding_completion_hash": decision.binding_completion_hash,
        "result_status": "changed",
        "prior_projection_hash": decision.prior_projection_hash,
        "prior_provider_version_hash": decision.prior_provider_version_hash,
        "observed_projection_hash": decision.observed_projection_hash,
        "observed_version_token_hash": decision.observed_version_token_hash,
        "authorized_by_id": decision.decided_by_id,
    }
    for field, value in expected.items():
        if getattr(authorization, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Observation refresh authorization snapshot drifted at {field}"
            )
    if (
        authorization.execution_limit != 1
        or authorization.status != "authorized"
        or _aware(authorization.authorized_at) != _aware(decision.decided_at)
        or authorization.scope_hash != _authorization_scope_hash(authorization)
        or authorization.authorization_hash != _authorization_hash(authorization)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh authorization cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(authorization, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh authorization safety boundary drifted"
            )


def ensure_observation_review_decision_integrity(
    db: Session,
    decision: ExternalDocumentSourceObservationReviewDecision,
) -> None:
    _ensure_decision_core_integrity(db, decision)
    authorization = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAuthorization).where(
            ExternalDocumentSourceObservationRefreshAuthorization.decision_id
            == decision.id
        )
    )
    if decision.decision_kind == "approve_refresh":
        if authorization is None:
            raise ExternalDocumentSourceConflictError(
                "Approved review decision lacks refresh authorization"
            )
        ensure_observation_refresh_authorization_integrity(db, authorization)
    elif authorization is not None:
        raise ExternalDocumentSourceConflictError(
            "Non-approval review decision unexpectedly has refresh authorization"
        )


def decide_observation_review_handoff(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    handoff_id: UUID,
    decided_by_id: UUID,
    request_key: str,
    decision_kind: str,
    decision_reason: str,
    now: datetime | None = None,
) -> tuple[
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationRefreshAuthorization | None,
    str,
]:
    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        decision_reason,
        field="reason",
        minimum=20,
        maximum=2000,
    )
    normalized_kind = decision_kind.strip().lower()
    status = _status_for_decision(normalized_kind)

    existing_request = db.scalar(
        select(ExternalDocumentSourceObservationReviewDecision).where(
            ExternalDocumentSourceObservationReviewDecision.organization_id
            == organization_id,
            ExternalDocumentSourceObservationReviewDecision.profile_id
            == profile_id,
            ExternalDocumentSourceObservationReviewDecision.request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_observation_review_decision_integrity(db, existing_request)
        if (
            existing_request.handoff_id != handoff_id
            or existing_request.decided_by_id != decided_by_id
            or existing_request.decision_kind != normalized_kind
            or existing_request.decision_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "request_key is already bound to another observation review decision"
            )
        authorization = db.scalar(
            select(ExternalDocumentSourceObservationRefreshAuthorization).where(
                ExternalDocumentSourceObservationRefreshAuthorization.decision_id
                == existing_request.id
            )
        )
        return existing_request, authorization, "replayed"

    handoff = db.scalar(
        select(ExternalDocumentSourceObservationReviewHandoff)
        .where(
            ExternalDocumentSourceObservationReviewHandoff.id == handoff_id,
            ExternalDocumentSourceObservationReviewHandoff.organization_id
            == organization_id,
            ExternalDocumentSourceObservationReviewHandoff.profile_id == profile_id,
        )
        .with_for_update()
    )
    if handoff is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation review handoff not found"
        )
    ensure_observation_review_handoff_integrity(db, handoff)
    _validate_matrix(
        result_status=handoff.result_status,
        decision_kind=normalized_kind,
    )

    existing_handoff = db.scalar(
        select(ExternalDocumentSourceObservationReviewDecision).where(
            ExternalDocumentSourceObservationReviewDecision.handoff_id == handoff.id
        )
    )
    if existing_handoff is not None:
        ensure_observation_review_decision_integrity(db, existing_handoff)
        if (
            existing_handoff.request_key != normalized_key
            or existing_handoff.decided_by_id != decided_by_id
            or existing_handoff.decision_kind != normalized_kind
            or existing_handoff.decision_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Observation review handoff already has a different terminal decision"
            )
        authorization = db.scalar(
            select(ExternalDocumentSourceObservationRefreshAuthorization).where(
                ExternalDocumentSourceObservationRefreshAuthorization.decision_id
                == existing_handoff.id
            )
        )
        return existing_handoff, authorization, "replayed"

    profile = get_external_document_source_profile(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
    )
    if (
        profile.status != "active"
        or profile.provider_kind != handoff.provider_kind
        or profile.profile_hash != handoff.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff no longer matches active source profile authority"
        )

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=handoff.binding_id,
    )
    if (
        binding.claim_id != handoff.claim_id
        or binding.document_family_id != handoff.document_family_id
        or binding.provider_kind != handoff.provider_kind
        or binding.profile_hash != handoff.profile_hash
        or binding.stable_source_item_hash != handoff.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff no longer matches current family binding authority"
        )

    current = _lock_current_family_document(
        db,
        organization_id=organization_id,
        claim_id=handoff.claim_id,
        document_family_id=handoff.document_family_id,
    )
    if (
        current.id != handoff.observed_document_id
        or current.version_number != handoff.observed_version_number
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation review handoff is stale because canonical Evidence changed"
        )

    prior_projection_hash, prior_provider_version_hash = _prior_source_state(
        db,
        binding=binding,
        current_document=current,
    )
    if (
        handoff.result_status == "changed"
        and handoff.observed_projection_hash == prior_projection_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Changed review handoff no longer differs from canonical source state"
        )

    decided_at = _aware(now or _utc_now())
    decision = ExternalDocumentSourceObservationReviewDecision(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=handoff.claim_id,
        profile_id=profile_id,
        handoff_id=handoff.id,
        observation_execution_id=handoff.observation_execution_id,
        schedule_id=handoff.schedule_id,
        binding_id=handoff.binding_id,
        document_family_id=handoff.document_family_id,
        current_document_id=current.id,
        current_version_number=current.version_number,
        current_document_file_hash=current.file_hash,
        result_status=handoff.result_status,
        provider_kind=handoff.provider_kind,
        profile_hash=handoff.profile_hash,
        stable_source_item_hash=handoff.stable_source_item_hash,
        handoff_completion_hash=handoff.completion_hash,
        binding_completion_hash=binding.completion_hash,
        prior_projection_hash=prior_projection_hash,
        prior_provider_version_hash=prior_provider_version_hash,
        observed_projection_hash=handoff.observed_projection_hash,
        observed_version_token_hash=handoff.observed_version_token_hash,
        request_key=normalized_key,
        decision_kind=normalized_kind,
        status=status,
        decided_by_id=decided_by_id,
        decision_reason=normalized_reason,
        decided_at=decided_at,
        scope_hash="",
        request_hash="",
        completion_hash="",
        **_safety(),
    )
    decision.scope_hash = _scope_hash(
        handoff=handoff,
        current=current,
        binding_completion_hash=binding.completion_hash,
        prior_projection_hash=prior_projection_hash,
        prior_provider_version_hash=prior_provider_version_hash,
        request_key=normalized_key,
    )
    decision.request_hash = _request_hash(decision)
    decision.completion_hash = _completion_hash(decision)
    db.add(decision)
    db.flush()

    receipt = ExternalDocumentSourceObservationReviewDecisionReceipt(
        id=uuid4(),
        organization_id=organization_id,
        decision_id=decision.id,
        sequence_number=1,
        event_type=normalized_kind,
        status_after=status,
        actor_id=decided_by_id,
        occurred_at=decided_at,
        reason=normalized_reason,
        scope_hash=decision.scope_hash,
        decision_hash=decision.completion_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()

    authorization = None
    if normalized_kind == "approve_refresh":
        if handoff.observed_projection_hash is None:
            raise ExternalDocumentSourceConflictError(
                "Changed review handoff lacks an observed projection"
            )
        authorization = ExternalDocumentSourceObservationRefreshAuthorization(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=handoff.claim_id,
            profile_id=profile_id,
            handoff_id=handoff.id,
            decision_id=decision.id,
            binding_id=handoff.binding_id,
            document_family_id=handoff.document_family_id,
            current_document_id=current.id,
            current_version_number=current.version_number,
            current_document_file_hash=current.file_hash,
            provider_kind=handoff.provider_kind,
            profile_hash=handoff.profile_hash,
            stable_source_item_hash=handoff.stable_source_item_hash,
            handoff_completion_hash=handoff.completion_hash,
            decision_completion_hash=decision.completion_hash,
            binding_completion_hash=binding.completion_hash,
            result_status="changed",
            prior_projection_hash=prior_projection_hash,
            prior_provider_version_hash=prior_provider_version_hash,
            observed_projection_hash=handoff.observed_projection_hash,
            observed_version_token_hash=handoff.observed_version_token_hash,
            execution_limit=1,
            status="authorized",
            authorized_by_id=decided_by_id,
            authorized_at=decided_at,
            scope_hash="",
            authorization_hash="",
            **_safety(),
        )
        authorization.scope_hash = _authorization_scope_hash(authorization)
        authorization.authorization_hash = _authorization_hash(authorization)
        db.add(authorization)
        db.flush()

    ensure_observation_review_decision_integrity(db, decision)

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=decided_by_id,
        action="DECIDE_EXTERNAL_EVIDENCE_OBSERVATION_REVIEW_HANDOFF",
        entity_type="external_document_source_observation_review_decision",
        entity_id=decision.id,
        new_values={
            "handoff_id": str(handoff.id),
            "decision_kind": normalized_kind,
            "status": status,
            "result_status": handoff.result_status,
            "refresh_authorization_id": str(authorization.id)
            if authorization is not None
            else None,
            "current_document_id": str(current.id),
            "current_version_number": current.version_number,
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
    db.refresh(decision)
    if authorization is not None:
        db.refresh(authorization)
    return decision, authorization, "decided"


def get_observation_review_decision(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    decision_id: UUID,
) -> ExternalDocumentSourceObservationReviewDecision:
    decision = db.scalar(
        select(ExternalDocumentSourceObservationReviewDecision).where(
            ExternalDocumentSourceObservationReviewDecision.id == decision_id,
            ExternalDocumentSourceObservationReviewDecision.organization_id
            == organization_id,
            ExternalDocumentSourceObservationReviewDecision.profile_id == profile_id,
        )
    )
    if decision is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation review decision not found"
        )
    ensure_observation_review_decision_integrity(db, decision)
    return decision


def list_observation_review_decision_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    decision_id: UUID,
) -> list[ExternalDocumentSourceObservationReviewDecisionReceipt]:
    decision = get_observation_review_decision(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        decision_id=decision_id,
    )
    return _decision_receipts(db, decision)


def get_observation_refresh_authorization_for_decision(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    decision_id: UUID,
) -> ExternalDocumentSourceObservationRefreshAuthorization | None:
    decision = get_observation_review_decision(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        decision_id=decision_id,
    )
    authorization = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAuthorization).where(
            ExternalDocumentSourceObservationRefreshAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAuthorization.profile_id == profile_id,
            ExternalDocumentSourceObservationRefreshAuthorization.decision_id
            == decision.id,
        )
    )
    if authorization is not None:
        ensure_observation_refresh_authorization_integrity(db, authorization)
    return authorization
