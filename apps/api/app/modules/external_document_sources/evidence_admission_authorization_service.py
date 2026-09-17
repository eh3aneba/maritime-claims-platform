from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
    ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.external_document_sources.generation_3_change_detection_service import (
    get_external_document_source_generation_3_change_detection,
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


def _safety() -> dict[str, bool]:
    return {
        "upstream_checkpoint_generation_3_advance_completed": True,
        "upstream_generation_3_change_detection_completed": True,
        "latest_generation_3_observation_confirmed": True,
        "remote_version_current_at_authorization": True,
        "human_authorization_recorded": True,
        "provider_client_constructed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "document_created": False,
        "evidence_admitted": False,
        "content_parsed": False,
        "content_extracted": False,
        "claim_mutated": False,
        "admission_execution_performed": False,
        "background_sync_started": False,
    }


def _scope_hash(
    *,
    organization_id: UUID,
    claim_id: UUID,
    profile_id: UUID,
    observation: ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "profile_id": str(profile_id),
            "generation_3_change_detection_execution_id": str(observation.id),
            "checkpoint_generation_3_execution_id": str(observation.checkpoint_generation_3_execution_id),
            "provider_kind": observation.provider_kind,
            "profile_hash": observation.profile_hash,
            "authorized_projection_hash": observation.observed_projection_hash,
            "checkpoint_state_hash": observation.successor_checkpoint_state_hash,
            "checkpoint_completion_hash": observation.successor_checkpoint_completion_hash,
            "candidate_content_proof_hash": observation.candidate_content_proof_hash,
            "candidate_completion_hash": observation.candidate_completion_hash,
            "observation_completion_hash": observation.completion_hash,
            "request_key": request_key,
        }
    )


def _request_hash(authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "authorized_by_id": str(authorization.authorized_by_id),
            "authorization_reason": authorization.authorization_reason,
            "authorized_at": _iso(authorization.authorized_at),
            **_safety(),
        }
    )


def _authorization_hash(authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "request_hash": authorization.request_hash,
            "status": authorization.status,
            "claim_id": str(authorization.claim_id),
            "generation_3_change_detection_execution_id": str(
                authorization.generation_3_change_detection_execution_id
            ),
            "authorized_projection_hash": authorization.authorized_projection_hash,
            "authorized_display_name_hash": authorization.authorized_display_name_hash,
            "authorized_version_token_hash": authorization.authorized_version_token_hash,
            "authorized_byte_size": authorization.authorized_byte_size,
            "authorized_mime_type_class": authorization.authorized_mime_type_class,
            "observation_completion_hash": authorization.observation_completion_hash,
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "authorization_id": str(receipt.authorization_id),
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


def _active_claim(db: Session, *, organization_id: UUID, claim_id: UUID) -> Claim:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.organization_id == organization_id,
            Claim.deleted_at.is_(None),
        )
    )
    if claim is None:
        raise ExternalDocumentSourceNotFoundError("Claim not found")
    return claim


def _latest_completed_observation(
    db: Session,
    *,
    observation: ExternalDocumentSourceGeneration3ChangeDetectionExecution,
) -> ExternalDocumentSourceGeneration3ChangeDetectionExecution | None:
    return db.scalar(
        select(ExternalDocumentSourceGeneration3ChangeDetectionExecution)
        .where(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.organization_id
            == observation.organization_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id
            == observation.profile_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.checkpoint_generation_3_execution_id
            == observation.checkpoint_generation_3_execution_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.status == "completed",
        )
        .order_by(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.completed_at.desc(),
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.created_at.desc(),
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.id.desc(),
        )
        .limit(1)
    )


def _eligible_observation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    require_latest: bool,
) -> ExternalDocumentSourceGeneration3ChangeDetectionExecution:
    observation = get_external_document_source_generation_3_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    if (
        observation.status != "completed"
        or observation.result_status != "unchanged"
        or observation.observed_projection_hash is None
        or observation.observed_projection_hash != observation.baseline_projection_hash
        or observation.observed_item_kind != "file"
        or observation.observed_display_name_hash is None
        or observation.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase V observation is not an unchanged complete file observation eligible for authorization"
        )
    if require_latest:
        latest = _latest_completed_observation(db, observation=observation)
        if latest is None or latest.id != observation.id:
            raise ExternalDocumentSourceConflictError(
                "Phase V observation is stale because a newer completed generation-3 observation exists"
            )
    return observation


def _receipts(
    db: Session,
    authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization,
) -> list[ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt)
            .where(
                ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt.organization_id
                == authorization.organization_id,
                ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt.authorization_id
                == authorization.id,
            )
            .order_by(ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt.sequence_number.asc())
        ).all()
    )


def _ensure_integrity(
    db: Session,
    authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization,
) -> None:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == authorization.claim_id,
            Claim.organization_id == authorization.organization_id,
        )
    )
    if claim is None:
        raise ExternalDocumentSourceConflictError("Authorized Claim lineage is missing")

    observation = _eligible_observation(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        execution_id=authorization.generation_3_change_detection_execution_id,
        require_latest=False,
    )
    expected = {
        "checkpoint_generation_3_execution_id": observation.checkpoint_generation_3_execution_id,
        "provider_kind": observation.provider_kind,
        "profile_hash": observation.profile_hash,
        "authorized_projection_hash": observation.observed_projection_hash,
        "authorized_display_name_hash": observation.observed_display_name_hash,
        "authorized_version_token_hash": observation.observed_version_token_hash,
        "authorized_byte_size": observation.observed_byte_size,
        "authorized_mime_type_class": observation.observed_mime_type_class,
        "checkpoint_state_hash": observation.successor_checkpoint_state_hash,
        "checkpoint_completion_hash": observation.successor_checkpoint_completion_hash,
        "candidate_content_proof_hash": observation.candidate_content_proof_hash,
        "candidate_completion_hash": observation.candidate_completion_hash,
        "observation_completion_hash": observation.completion_hash,
    }
    for field, expected_value in expected.items():
        if getattr(authorization, field) != expected_value:
            raise ExternalDocumentSourceConflictError(
                f"Evidence admission authorization integrity drifted at {field}"
            )

    if authorization.status != "authorized":
        raise ExternalDocumentSourceConflictError("Evidence admission authorization lifecycle drifted")
    expected_scope = _scope_hash(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        profile_id=authorization.profile_id,
        observation=observation,
        request_key=authorization.request_key,
    )
    if authorization.scope_hash != expected_scope:
        raise ExternalDocumentSourceConflictError("Evidence admission authorization scope hash drifted")
    if authorization.request_hash != _request_hash(authorization):
        raise ExternalDocumentSourceConflictError("Evidence admission authorization request hash drifted")
    if authorization.authorization_hash != _authorization_hash(authorization):
        raise ExternalDocumentSourceConflictError("Evidence admission authorization decision hash drifted")

    rows = _receipts(db, authorization)
    if len(rows) != 1:
        raise ExternalDocumentSourceConflictError("Evidence admission authorization receipt lifecycle drifted")
    receipt = rows[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "authorized"
        or receipt.status_after != "authorized"
        or receipt.actor_id != authorization.authorized_by_id
        or _aware(receipt.occurred_at) != _aware(authorization.authorized_at)
        or receipt.reason != authorization.authorization_reason
        or receipt.scope_hash != authorization.scope_hash
        or receipt.decision_hash != authorization.authorization_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError("Evidence admission authorization receipt integrity drifted")


def authorize_external_document_source_evidence_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    generation_3_change_detection_execution_id: UUID,
    claim_id: UUID,
    authorized_by_id: UUID,
    request_key: str,
    authorization_reason: str,
) -> tuple[ExternalDocumentSourceEvidenceAdmissionAuthorization, str]:
    request_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    authorization_reason = _normalize_text(
        authorization_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceEvidenceAdmissionAuthorization.organization_id == organization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.profile_id == profile_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.request_key == request_key,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.claim_id != claim_id
            or existing.generation_3_change_detection_execution_id
            != generation_3_change_detection_execution_id
            or existing.authorized_by_id != authorized_by_id
            or existing.authorization_reason != authorization_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "request_key is already bound to a different evidence admission authorization"
            )
        return existing, "replayed"

    _active_claim(db, organization_id=organization_id, claim_id=claim_id)
    observation = _eligible_observation(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=generation_3_change_detection_execution_id,
        require_latest=True,
    )

    authorized_at = _utc_now()
    authorization = ExternalDocumentSourceEvidenceAdmissionAuthorization(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=claim_id,
        profile_id=profile_id,
        generation_3_change_detection_execution_id=observation.id,
        checkpoint_generation_3_execution_id=observation.checkpoint_generation_3_execution_id,
        provider_kind=observation.provider_kind,
        profile_hash=observation.profile_hash,
        authorized_projection_hash=observation.observed_projection_hash,
        authorized_display_name_hash=observation.observed_display_name_hash,
        authorized_version_token_hash=observation.observed_version_token_hash,
        authorized_byte_size=observation.observed_byte_size,
        authorized_mime_type_class=observation.observed_mime_type_class,
        checkpoint_state_hash=observation.successor_checkpoint_state_hash,
        checkpoint_completion_hash=observation.successor_checkpoint_completion_hash,
        candidate_content_proof_hash=observation.candidate_content_proof_hash,
        candidate_completion_hash=observation.candidate_completion_hash,
        observation_completion_hash=observation.completion_hash,
        request_key=request_key,
        scope_hash=_scope_hash(
            organization_id=organization_id,
            claim_id=claim_id,
            profile_id=profile_id,
            observation=observation,
            request_key=request_key,
        ),
        request_hash="",
        status="authorized",
        authorized_by_id=authorized_by_id,
        authorization_reason=authorization_reason,
        authorized_at=authorized_at,
        authorization_hash="",
        **_safety(),
    )
    authorization.request_hash = _request_hash(authorization)
    authorization.authorization_hash = _authorization_hash(authorization)
    db.add(authorization)
    db.flush()

    receipt = ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt(
        id=uuid4(),
        organization_id=organization_id,
        authorization_id=authorization.id,
        sequence_number=1,
        event_type="authorized",
        status_after="authorized",
        actor_id=authorized_by_id,
        occurred_at=authorized_at,
        reason=authorization_reason,
        scope_hash=authorization.scope_hash,
        decision_hash=authorization.authorization_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    _ensure_integrity(db, authorization)
    return authorization, "authorized"


def get_external_document_source_evidence_admission_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceEvidenceAdmissionAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceEvidenceAdmissionAuthorization.id == authorization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.organization_id == organization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.profile_id == profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError("Evidence admission authorization not found")
    _ensure_integrity(db, authorization)
    return authorization


def list_external_document_source_evidence_admission_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> list[ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt]:
    authorization = get_external_document_source_evidence_admission_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    return _receipts(db, authorization)
