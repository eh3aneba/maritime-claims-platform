from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _binding_for_update,
    _lock_current_family_document,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    ensure_observation_refresh_execution_integrity,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    _require_human_admin,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
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
        "refresh_execution_verified": True,
        "durable_family_binding_verified": True,
        "stable_source_identity_verified": True,
        "current_document_verified": True,
        "staged_content_proof_verified": True,
        "human_authorization_recorded": True,
        "provider_client_constructed": False,
        "oauth_token_acquired": False,
        "remote_list_performed": False,
        "remote_metadata_read_performed": False,
        "remote_content_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "file_signature_validated": False,
        "malware_scan_completed": False,
        "document_mutated": False,
        "evidence_admitted": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_sync_started": False,
    }


def _scope_hash(
    refresh: ExternalDocumentSourceObservationRefreshExecution,
    current: Document,
    *,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(refresh.organization_id),
            "claim_id": str(refresh.claim_id),
            "profile_id": str(refresh.profile_id),
            "refresh_execution_id": str(refresh.id),
            "refresh_authorization_id": str(refresh.authorization_id),
            "decision_id": str(refresh.decision_id),
            "handoff_id": str(refresh.handoff_id),
            "binding_id": str(refresh.binding_id),
            "document_family_id": str(refresh.document_family_id),
            "expected_prior_document_id": str(current.id),
            "expected_prior_version_number": current.version_number,
            "prior_document_file_hash": current.file_hash,
            "provider_kind": refresh.provider_kind,
            "profile_hash": refresh.profile_hash,
            "stable_source_item_hash": refresh.stable_source_item_hash,
            "refresh_authorization_hash": refresh.authorization_hash,
            "refresh_completion_hash": refresh.completion_hash,
            "decision_completion_hash": refresh.decision_completion_hash,
            "handoff_completion_hash": refresh.handoff_completion_hash,
            "binding_completion_hash": refresh.binding_completion_hash,
            "observed_projection_hash": refresh.observed_projection_hash,
            "observed_version_token_hash": refresh.observed_version_token_hash,
            "refreshed_content_sha256": refresh.content_sha256,
            "refreshed_content_byte_count": refresh.content_byte_count,
            "refreshed_content_media_type_class": refresh.content_media_type_class,
            "refreshed_content_version_token_hash": refresh.content_version_token_hash,
            "refreshed_content_proof_hash": refresh.content_proof_hash,
            "storage_backend_kind": refresh.storage_backend_kind,
            "storage_purpose": refresh.storage_purpose,
            "storage_object_key_hash": refresh.storage_object_key_hash,
            "request_key": request_key,
        }
    )


def _request_hash(
    *,
    scope_hash: str,
    authorized_by_id: UUID,
    reason: str,
    authorized_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "scope_hash": scope_hash,
            "authorized_by_id": str(authorized_by_id),
            "authorization_reason": reason,
            "authorized_at": _iso(authorized_at),
        }
    )


def _authorization_hash(
    authorization: ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "request_hash": authorization.request_hash,
            "status": authorization.status,
            "refresh_completion_hash": authorization.refresh_completion_hash,
            "refreshed_content_proof_hash": authorization.refreshed_content_proof_hash,
            "refreshed_content_sha256": authorization.refreshed_content_sha256,
            "refreshed_content_byte_count": authorization.refreshed_content_byte_count,
            "storage_object_key_hash": authorization.storage_object_key_hash,
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt,
) -> str:
    return _canonical_hash(
        {
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


def _receipts(
    db: Session,
    authorization: ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
) -> list[ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt)
            .where(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt.organization_id
                == authorization.organization_id,
                ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt.authorization_id
                == authorization.id,
            )
            .order_by(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt.sequence_number.asc()
            )
        ).all()
    )


def _refresh_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    refresh_execution_id: UUID,
) -> ExternalDocumentSourceObservationRefreshExecution:
    refresh = db.scalar(
        select(ExternalDocumentSourceObservationRefreshExecution)
        .where(
            ExternalDocumentSourceObservationRefreshExecution.id == refresh_execution_id,
            ExternalDocumentSourceObservationRefreshExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshExecution.profile_id == profile_id,
        )
        .with_for_update()
    )
    if refresh is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation refresh execution not found"
        )
    ensure_observation_refresh_execution_integrity(
        db,
        refresh,
        verify_storage=False,
    )
    if (
        refresh.status != "completed"
        or refresh.result_status != "staged_refresh_verified"
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh execution is not eligible for admission authorization"
        )
    return refresh


def ensure_observation_refresh_admission_authorization_integrity(
    db: Session,
    authorization: ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
) -> None:
    refresh = db.get(
        ExternalDocumentSourceObservationRefreshExecution,
        authorization.refresh_execution_id,
    )
    if refresh is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization refresh execution is missing"
        )
    ensure_observation_refresh_execution_integrity(
        db,
        refresh,
        verify_storage=False,
    )
    binding = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding).where(
            ExternalDocumentSourceEvidenceFamilyBinding.id == authorization.binding_id,
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == authorization.organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id
            == authorization.profile_id,
        )
    )
    if binding is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization family binding is missing"
        )
    _ensure_binding_integrity(db, binding)
    prior = db.get(Document, authorization.expected_prior_document_id)
    if prior is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization prior Document is missing"
        )

    expected = {
        "organization_id": refresh.organization_id,
        "claim_id": refresh.claim_id,
        "profile_id": refresh.profile_id,
        "refresh_authorization_id": refresh.authorization_id,
        "decision_id": refresh.decision_id,
        "handoff_id": refresh.handoff_id,
        "binding_id": refresh.binding_id,
        "document_family_id": refresh.document_family_id,
        "expected_prior_document_id": refresh.current_document_id,
        "expected_prior_version_number": refresh.current_version_number,
        "provider_kind": refresh.provider_kind,
        "profile_hash": refresh.profile_hash,
        "stable_source_item_hash": refresh.stable_source_item_hash,
        "refresh_authorization_hash": refresh.authorization_hash,
        "refresh_completion_hash": refresh.completion_hash,
        "decision_completion_hash": refresh.decision_completion_hash,
        "handoff_completion_hash": refresh.handoff_completion_hash,
        "binding_completion_hash": refresh.binding_completion_hash,
        "observed_projection_hash": refresh.observed_projection_hash,
        "observed_version_token_hash": refresh.observed_version_token_hash,
        "prior_document_file_hash": refresh.current_document_file_hash,
        "refreshed_content_sha256": refresh.content_sha256,
        "refreshed_content_byte_count": refresh.content_byte_count,
        "refreshed_content_media_type_class": refresh.content_media_type_class,
        "refreshed_content_version_token_hash": refresh.content_version_token_hash,
        "refreshed_content_proof_hash": refresh.content_proof_hash,
        "storage_backend_kind": refresh.storage_backend_kind,
        "storage_purpose": refresh.storage_purpose,
        "storage_object_key_hash": refresh.storage_object_key_hash,
        "status": "authorized",
    }
    for field, value in expected.items():
        if getattr(authorization, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Observation refresh admission authorization snapshot drifted at {field}"
            )

    if (
        prior.organization_id != authorization.organization_id
        or prior.claim_id != authorization.claim_id
        or prior.document_family_id != authorization.document_family_id
        or prior.version_number != authorization.expected_prior_version_number
        or prior.file_hash != authorization.prior_document_file_hash
        or binding.claim_id != authorization.claim_id
        or binding.document_family_id != authorization.document_family_id
        or binding.provider_kind != authorization.provider_kind
        or binding.profile_hash != authorization.profile_hash
        or binding.stable_source_item_hash != authorization.stable_source_item_hash
        or binding.completion_hash != authorization.binding_completion_hash
        or authorization.refreshed_content_sha256
        == authorization.prior_document_file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization source/family lineage drifted"
        )

    expected_scope = _scope_hash(
        refresh,
        prior,
        request_key=authorization.request_key,
    )
    expected_request = _request_hash(
        scope_hash=expected_scope,
        authorized_by_id=authorization.authorized_by_id,
        reason=authorization.authorization_reason,
        authorized_at=authorization.authorized_at,
    )
    if (
        authorization.scope_hash != expected_scope
        or authorization.request_hash != expected_request
        or authorization.authorization_hash != _authorization_hash(authorization)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(authorization, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission authorization safety boundary drifted"
            )

    receipts = _receipts(db, authorization)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization receipt lifecycle drifted"
        )
    receipt = receipts[0]
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
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission authorization receipt safety boundary drifted"
            )


def authorize_observation_refresh_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    refresh_execution_id: UUID,
    authorized_by_id: UUID,
    request_key: str,
    authorization_reason: str,
    now: datetime | None = None,
) -> tuple[
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
    str,
]:
    _require_human_admin(
        db,
        organization_id=organization_id,
        user_id=authorized_by_id,
    )
    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        authorization_reason,
        field="reason",
        minimum=20,
        maximum=2000,
    )

    existing_request = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionAuthorization).where(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.profile_id
            == profile_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_observation_refresh_admission_authorization_integrity(
            db,
            existing_request,
        )
        if (
            existing_request.refresh_execution_id != refresh_execution_id
            or existing_request.authorized_by_id != authorized_by_id
            or existing_request.authorization_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "request_key is already bound to another observation refresh admission authorization"
            )
        return existing_request, "replayed"

    refresh = _refresh_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        refresh_execution_id=refresh_execution_id,
    )

    existing_refresh = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionAuthorization).where(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.refresh_execution_id
            == refresh.id
        )
    )
    if existing_refresh is not None:
        ensure_observation_refresh_admission_authorization_integrity(
            db,
            existing_refresh,
        )
        if (
            existing_refresh.request_key == normalized_key
            and existing_refresh.authorized_by_id == authorized_by_id
            and existing_refresh.authorization_reason == normalized_reason
        ):
            return existing_refresh, "replayed"
        raise ExternalDocumentSourceConflictError(
            "Observation refresh execution is already bound to another admission authorization"
        )

    profile = _get_profile(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        for_update=False,
    )
    _ensure_profile_integrity(db, profile)
    if (
        profile.status != "active"
        or profile.provider_kind != refresh.provider_kind
        or profile.profile_hash != refresh.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization profile authority drifted"
        )

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=refresh.binding_id,
    )
    if (
        binding.status != "active"
        or binding.claim_id != refresh.claim_id
        or binding.document_family_id != refresh.document_family_id
        or binding.provider_kind != refresh.provider_kind
        or binding.profile_hash != refresh.profile_hash
        or binding.stable_source_item_hash != refresh.stable_source_item_hash
        or binding.completion_hash != refresh.binding_completion_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization family binding drifted"
        )

    current = _lock_current_family_document(
        db,
        organization_id=organization_id,
        claim_id=refresh.claim_id,
        document_family_id=refresh.document_family_id,
        expected_current_document_id=refresh.current_document_id,
    )
    if (
        current.version_number != refresh.current_version_number
        or current.file_hash != refresh.current_document_file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization is stale because canonical Evidence changed"
        )
    if refresh.content_sha256 == current.file_hash:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh content is identical to the current canonical Evidence"
        )

    duplicate = db.scalar(
        select(Document.id).where(
            Document.organization_id == organization_id,
            Document.claim_id == refresh.claim_id,
            Document.file_hash == refresh.content_sha256,
            Document.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh content already exists in Claim Evidence"
        )

    authorized_at = now or _utc_now()
    authorization = ExternalDocumentSourceObservationRefreshAdmissionAuthorization(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=refresh.claim_id,
        profile_id=profile_id,
        refresh_execution_id=refresh.id,
        refresh_authorization_id=refresh.authorization_id,
        decision_id=refresh.decision_id,
        handoff_id=refresh.handoff_id,
        binding_id=refresh.binding_id,
        document_family_id=refresh.document_family_id,
        expected_prior_document_id=current.id,
        expected_prior_version_number=current.version_number,
        provider_kind=refresh.provider_kind,
        profile_hash=refresh.profile_hash,
        stable_source_item_hash=refresh.stable_source_item_hash,
        refresh_authorization_hash=refresh.authorization_hash,
        refresh_completion_hash=refresh.completion_hash,
        decision_completion_hash=refresh.decision_completion_hash,
        handoff_completion_hash=refresh.handoff_completion_hash,
        binding_completion_hash=refresh.binding_completion_hash,
        observed_projection_hash=refresh.observed_projection_hash,
        observed_version_token_hash=refresh.observed_version_token_hash,
        prior_document_file_hash=current.file_hash,
        refreshed_content_sha256=refresh.content_sha256,
        refreshed_content_byte_count=refresh.content_byte_count,
        refreshed_content_media_type_class=refresh.content_media_type_class,
        refreshed_content_version_token_hash=refresh.content_version_token_hash,
        refreshed_content_proof_hash=refresh.content_proof_hash,
        storage_backend_kind=refresh.storage_backend_kind,
        storage_purpose=refresh.storage_purpose,
        storage_object_key_hash=refresh.storage_object_key_hash,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="authorized",
        authorized_by_id=authorized_by_id,
        authorization_reason=normalized_reason,
        authorized_at=authorized_at,
        authorization_hash="",
        **_safety(),
    )
    authorization.scope_hash = _scope_hash(
        refresh,
        current,
        request_key=normalized_key,
    )
    authorization.request_hash = _request_hash(
        scope_hash=authorization.scope_hash,
        authorized_by_id=authorized_by_id,
        reason=normalized_reason,
        authorized_at=authorized_at,
    )
    authorization.authorization_hash = _authorization_hash(authorization)
    db.add(authorization)
    db.flush()

    receipt = ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt(
        id=uuid4(),
        organization_id=organization_id,
        authorization_id=authorization.id,
        sequence_number=1,
        event_type="authorized",
        status_after="authorized",
        actor_id=authorized_by_id,
        occurred_at=authorized_at,
        reason=normalized_reason,
        scope_hash=authorization.scope_hash,
        decision_hash=authorization.authorization_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()

    ensure_observation_refresh_admission_authorization_integrity(
        db,
        authorization,
    )
    db.commit()
    db.refresh(authorization)
    return authorization, "authorized"


def get_observation_refresh_admission_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceObservationRefreshAdmissionAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionAuthorization).where(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.id
            == authorization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.profile_id
            == profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation refresh admission authorization not found"
        )
    ensure_observation_refresh_admission_authorization_integrity(
        db,
        authorization,
    )
    return authorization


def list_observation_refresh_admission_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> list[ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt]:
    authorization = get_observation_refresh_admission_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    return _receipts(db, authorization)
