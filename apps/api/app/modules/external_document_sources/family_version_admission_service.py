from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.malware import MalwareScannerError, MalwareScanVerdict, scan_file
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
)
from app.modules.documents.service import (
    _storage,
    make_quarantine_key,
    make_storage_key,
    normalize_original_filename,
    settings,
    validate_file_signature,
    validate_upload,
)
from app.modules.documents.storage import StorageError
from app.modules.external_document_sources.credential_reference_health_service import (
    CredentialReferenceLocator,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
)
from app.modules.external_document_sources.family_version_admission_models import (
    ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
    ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt,
    ExternalDocumentSourceFamilyVersionAdmissionExecution,
    ExternalDocumentSourceFamilyVersionAdmissionReceipt,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    _configured_store,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    _active_binding,
    _health_execution,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
)
from app.modules.external_document_sources.successor_change_detection_service import (
    _OBSERVATION_ADAPTERS,
    _checkpoint_generation,
    _ensure_integrity as _ensure_successor_change_integrity,
    _lineage as _successor_lineage,
    _projection_hash,
    _validate_result,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
)
from app.modules.external_document_sources.successor_versioned_restaging_service import (
    _ensure_integrity as _ensure_candidate_integrity,
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


def _auth_safety() -> dict[str, bool]:
    return {
        "durable_family_binding_verified": True,
        "stable_source_identity_verified": True,
        "staged_candidate_verified": True,
        "current_document_verified": True,
        "human_authorization_recorded": True,
        "remote_metadata_read_performed": False,
        "remote_content_read_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "document_mutated": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_sync_started": False,
    }


def _exec_safety() -> dict[str, bool]:
    return {
        "authorization_verified": True,
        "durable_family_binding_verified": True,
        "stable_source_identity_verified": True,
        "authorization_single_use_consumed": True,
        "fresh_exact_item_metadata_read_performed": True,
        "fresh_remote_version_current": True,
        "staged_content_integrity_verified": True,
        "malware_scan_completed": True,
        "canonical_document_write_completed": True,
        "new_document_created": True,
        "prior_document_superseded": True,
        "exactly_one_current_version_established": True,
        "later_version_admitted": True,
        "remote_list_performed": False,
        "remote_content_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "staged_storage_write_performed": False,
        "staged_storage_delete_performed": False,
        "content_parsed": False,
        "content_extracted": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_sync_started": False,
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
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id == organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id == profile_id,
        )
        .with_for_update()
    )
    if binding is None:
        raise ExternalDocumentSourceNotFoundError(
            "External Evidence family binding not found"
        )
    _ensure_binding_integrity(db, binding)
    return binding


def _lock_current_family_document(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_family_id: UUID,
    expected_current_document_id: UUID | None = None,
) -> Document:
    current = db.scalar(
        select(Document)
        .where(
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
            Document.document_family_id == document_family_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if current is None:
        raise ExternalDocumentSourceConflictError(
            "Evidence family has no canonical current Document"
        )
    if (
        expected_current_document_id is not None
        and current.id != expected_current_document_id
    ):
        raise ExternalDocumentSourceConflictError(
            "Evidence family current Document changed after authorization"
        )
    return current


def _candidate(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    candidate_id: UUID,
    for_update: bool,
) -> ExternalDocumentSourceSuccessorVersionedRestagingExecution:
    stmt = select(ExternalDocumentSourceSuccessorVersionedRestagingExecution).where(
        ExternalDocumentSourceSuccessorVersionedRestagingExecution.id == candidate_id,
        ExternalDocumentSourceSuccessorVersionedRestagingExecution.organization_id
        == organization_id,
        ExternalDocumentSourceSuccessorVersionedRestagingExecution.profile_id
        == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "Later-version staged candidate not found"
        )
    _ensure_candidate_integrity(db, row, verify_storage=False)
    if (
        row.status != "completed"
        or row.result_status != "staged_candidate_verified"
        or row.content_sha256 is None
        or row.content_byte_count is None
        or row.content_proof_hash is None
        or row.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version staged candidate is incomplete"
        )
    return row


def _successor_change(
    db: Session,
    candidate: ExternalDocumentSourceSuccessorVersionedRestagingExecution,
) -> ExternalDocumentSourceSuccessorChangeDetectionExecution:
    change = db.scalar(
        select(ExternalDocumentSourceSuccessorChangeDetectionExecution).where(
            ExternalDocumentSourceSuccessorChangeDetectionExecution.id
            == candidate.successor_change_detection_execution_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.organization_id
            == candidate.organization_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.profile_id
            == candidate.profile_id,
        )
    )
    if change is None:
        raise ExternalDocumentSourceConflictError(
            "Later-version changed-observation lineage is missing"
        )
    _ensure_successor_change_integrity(db, change)
    if (
        change.status != "completed"
        or change.result_status != "changed"
        or change.observed_projection_hash is None
        or change.observed_provider_item_id_hash is None
        or change.observed_display_name_hash is None
        or change.completion_hash is None
        or candidate.observed_projection_hash != change.observed_projection_hash
        or candidate.observed_provider_item_id_hash
        != change.observed_provider_item_id_hash
        or candidate.observed_version_token_hash
        != change.observed_version_token_hash
        or candidate.observed_byte_size != change.observed_byte_size
        or candidate.observed_mime_type_class != change.observed_mime_type_class
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version staged candidate no longer matches its changed observation"
        )
    return change


def _latest_successor_change(
    db: Session,
    change: ExternalDocumentSourceSuccessorChangeDetectionExecution,
) -> ExternalDocumentSourceSuccessorChangeDetectionExecution | None:
    return db.scalar(
        select(ExternalDocumentSourceSuccessorChangeDetectionExecution)
        .where(
            ExternalDocumentSourceSuccessorChangeDetectionExecution.organization_id
            == change.organization_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.profile_id
            == change.profile_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.checkpoint_generation_execution_id
            == change.checkpoint_generation_execution_id,
            ExternalDocumentSourceSuccessorChangeDetectionExecution.status
            == "completed",
        )
        .order_by(
            ExternalDocumentSourceSuccessorChangeDetectionExecution.completed_at.desc(),
            ExternalDocumentSourceSuccessorChangeDetectionExecution.created_at.desc(),
            ExternalDocumentSourceSuccessorChangeDetectionExecution.id.desc(),
        )
        .limit(1)
    )


def _prior_source_state(
    db: Session,
    *,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    current_document: Document,
) -> tuple[str, str | None]:
    if current_document.version_number == 1:
        if (
            current_document.id != binding.initial_document_id
            or current_document.file_hash != binding.admitted_content_sha256
        ):
            raise ExternalDocumentSourceConflictError(
                "Initial external Evidence family provenance drifted"
            )
        return binding.source_projection_hash, binding.admitted_provider_version_hash

    prior_execution = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionExecution).where(
            ExternalDocumentSourceFamilyVersionAdmissionExecution.organization_id
            == binding.organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.binding_id == binding.id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.new_document_id
            == current_document.id,
        )
    )
    if prior_execution is None:
        raise ExternalDocumentSourceConflictError(
            "Current external Evidence family version lacks governed AA lineage"
        )
    _ensure_execution_integrity(db, prior_execution)
    if prior_execution.new_version_number != current_document.version_number:
        raise ExternalDocumentSourceConflictError(
            "Current external Evidence family version lineage drifted"
        )
    return prior_execution.fresh_projection_hash, prior_execution.fresh_version_token_hash


def _auth_scope_hash(
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    candidate: ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    change: ExternalDocumentSourceSuccessorChangeDetectionExecution,
    current_document: Document,
    *,
    prior_projection_hash: str,
    prior_provider_version_hash: str | None,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(binding.organization_id),
            "claim_id": str(binding.claim_id),
            "profile_id": str(binding.profile_id),
            "binding_id": str(binding.id),
            "binding_completion_hash": binding.completion_hash,
            "successor_change_detection_execution_id": str(change.id),
            "successor_change_completion_hash": change.completion_hash,
            "successor_versioned_restaging_execution_id": str(candidate.id),
            "candidate_content_proof_hash": candidate.content_proof_hash,
            "candidate_completion_hash": candidate.completion_hash,
            "document_family_id": str(binding.document_family_id),
            "expected_prior_document_id": str(current_document.id),
            "expected_prior_version_number": current_document.version_number,
            "prior_document_file_hash": current_document.file_hash,
            "prior_projection_hash": prior_projection_hash,
            "prior_provider_version_hash": prior_provider_version_hash,
            "stable_source_item_hash": binding.stable_source_item_hash,
            "authorized_projection_hash": change.observed_projection_hash,
            "candidate_content_sha256": candidate.content_sha256,
            "candidate_content_byte_count": candidate.content_byte_count,
            "request_key": request_key,
        }
    )


def _auth_request_hash(
    authorization: ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "authorized_by_id": str(authorization.authorized_by_id),
            "authorization_reason": authorization.authorization_reason,
            "authorized_at": _iso(authorization.authorized_at),
            **_auth_safety(),
        }
    )


def _authorization_hash(
    authorization: ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "scope_hash": authorization.scope_hash,
            "request_hash": authorization.request_hash,
            "status": authorization.status,
            "candidate_content_proof_hash": authorization.candidate_content_proof_hash,
            "candidate_completion_hash": authorization.candidate_completion_hash,
            "authorized_projection_hash": authorization.authorized_projection_hash,
            "candidate_content_sha256": authorization.candidate_content_sha256,
            "candidate_content_byte_count": authorization.candidate_content_byte_count,
            **_auth_safety(),
        }
    )


def _auth_receipt_hash(
    receipt: ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt,
) -> str:
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
            **_auth_safety(),
        }
    )


def _auth_receipts(
    db: Session,
    authorization: ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
) -> list[ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt)
            .where(
                ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt.organization_id
                == authorization.organization_id,
                ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt.authorization_id
                == authorization.id,
            )
            .order_by(
                ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt.sequence_number.asc()
            )
        ).all()
    )


def _ensure_authorization_integrity(
    db: Session,
    authorization: ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
) -> None:
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
            "Later-version authorization family binding is missing"
        )
    _ensure_binding_integrity(db, binding)

    candidate = _candidate(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        candidate_id=authorization.successor_versioned_restaging_execution_id,
        for_update=False,
    )
    change = _successor_change(db, candidate)
    prior = db.get(Document, authorization.expected_prior_document_id)
    if prior is None:
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization prior Document is missing"
        )

    expected = {
        "claim_id": binding.claim_id,
        "successor_change_detection_execution_id": change.id,
        "document_family_id": binding.document_family_id,
        "provider_kind": binding.provider_kind,
        "profile_hash": binding.profile_hash,
        "stable_source_item_hash": binding.stable_source_item_hash,
        "successor_change_completion_hash": change.completion_hash,
        "candidate_content_proof_hash": candidate.content_proof_hash,
        "candidate_completion_hash": candidate.completion_hash,
        "prior_document_file_hash": prior.file_hash,
        "authorized_projection_hash": change.observed_projection_hash,
        "authorized_display_name_hash": change.observed_display_name_hash,
        "authorized_version_token_hash": change.observed_version_token_hash,
        "authorized_byte_size": change.observed_byte_size,
        "authorized_mime_type_class": change.observed_mime_type_class,
        "candidate_content_sha256": candidate.content_sha256,
        "candidate_content_byte_count": candidate.content_byte_count,
        "candidate_storage_object_key_hash": candidate.storage_object_key_hash,
        "status": "authorized",
    }
    for field, value in expected.items():
        if getattr(authorization, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Later-version authorization integrity drifted at {field}"
            )
    if (
        prior.organization_id != authorization.organization_id
        or prior.claim_id != authorization.claim_id
        or prior.document_family_id != authorization.document_family_id
        or prior.version_number != authorization.expected_prior_version_number
        or change.observed_provider_item_id_hash
        != authorization.stable_source_item_hash
        or authorization.authorized_projection_hash
        == authorization.prior_projection_hash
        or authorization.candidate_content_sha256
        == authorization.prior_document_file_hash
        or (
            authorization.prior_provider_version_hash is not None
            and authorization.authorized_version_token_hash is not None
            and authorization.prior_provider_version_hash
            == authorization.authorized_version_token_hash
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization source/family lineage drifted"
        )

    expected_scope = _auth_scope_hash(
        binding,
        candidate,
        change,
        prior,
        prior_projection_hash=authorization.prior_projection_hash,
        prior_provider_version_hash=authorization.prior_provider_version_hash,
        request_key=authorization.request_key,
    )
    if (
        authorization.scope_hash != expected_scope
        or authorization.request_hash != _auth_request_hash(authorization)
        or authorization.authorization_hash != _authorization_hash(authorization)
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization cryptographic integrity failed"
        )
    for field, value in _auth_safety().items():
        if bool(getattr(authorization, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Later-version authorization safety boundary drifted"
            )

    receipts = _auth_receipts(db, authorization)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization receipt lifecycle drifted"
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
        or receipt.receipt_hash != _auth_receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization receipt integrity drifted"
        )
    for field, value in _auth_safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Later-version authorization receipt safety boundary drifted"
            )


def authorize_external_document_source_family_version_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    successor_versioned_restaging_execution_id: UUID,
    authorized_by_id: UUID,
    request_key: str,
    authorization_reason: str,
) -> tuple[ExternalDocumentSourceFamilyVersionAdmissionAuthorization, str]:
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

    existing = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionAuthorization).where(
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.profile_id
            == profile_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.request_key
            == normalized_key,
        )
    )
    if existing is not None:
        _ensure_authorization_integrity(db, existing)
        if (
            existing.binding_id != binding_id
            or existing.successor_versioned_restaging_execution_id
            != successor_versioned_restaging_execution_id
            or existing.authorized_by_id != authorized_by_id
            or existing.authorization_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "request_key is already bound to another later-version authorization"
            )
        return existing, "replayed"

    candidate = _candidate(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        candidate_id=successor_versioned_restaging_execution_id,
        for_update=True,
    )
    change = _successor_change(db, candidate)
    latest = _latest_successor_change(db, change)
    if latest is None or latest.id != change.id:
        raise ExternalDocumentSourceConflictError(
            "Later-version staged candidate is stale because a newer source observation exists"
        )

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    current = _lock_current_family_document(
        db,
        organization_id=organization_id,
        claim_id=binding.claim_id,
        document_family_id=binding.document_family_id,
    )
    prior_projection_hash, prior_provider_version_hash = _prior_source_state(
        db,
        binding=binding,
        current_document=current,
    )

    if (
        candidate.provider_kind != binding.provider_kind
        or candidate.profile_hash != binding.profile_hash
        or change.observed_provider_item_id_hash != binding.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version candidate does not belong to the bound external Evidence source"
        )
    if (
        change.observed_projection_hash == prior_projection_hash
        or candidate.content_sha256 == current.file_hash
        or (
            prior_provider_version_hash is not None
            and change.observed_version_token_hash is not None
            and prior_provider_version_hash == change.observed_version_token_hash
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version candidate is not newer than the current canonical Evidence version"
        )
    if (
        change.completed_at is None
        or candidate.completed_at is None
        or _aware(change.completed_at) < _aware(current.created_at)
        or _aware(candidate.completed_at) < _aware(change.completed_at)
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version candidate predates the current canonical Evidence version"
        )

    duplicate = db.scalar(
        select(Document.id).where(
            Document.organization_id == organization_id,
            Document.claim_id == binding.claim_id,
            Document.file_hash == candidate.content_sha256,
            Document.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ExternalDocumentSourceConflictError(
            "Later-version candidate bytes already exist in Claim Evidence"
        )

    authorized_at = _utc_now()
    authorization = ExternalDocumentSourceFamilyVersionAdmissionAuthorization(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=binding.claim_id,
        profile_id=profile_id,
        binding_id=binding.id,
        successor_change_detection_execution_id=change.id,
        successor_versioned_restaging_execution_id=candidate.id,
        document_family_id=binding.document_family_id,
        expected_prior_document_id=current.id,
        expected_prior_version_number=current.version_number,
        provider_kind=binding.provider_kind,
        profile_hash=binding.profile_hash,
        stable_source_item_hash=binding.stable_source_item_hash,
        successor_change_completion_hash=change.completion_hash,
        candidate_content_proof_hash=candidate.content_proof_hash,
        candidate_completion_hash=candidate.completion_hash,
        prior_projection_hash=prior_projection_hash,
        prior_provider_version_hash=prior_provider_version_hash,
        prior_document_file_hash=current.file_hash,
        authorized_projection_hash=change.observed_projection_hash,
        authorized_display_name_hash=change.observed_display_name_hash,
        authorized_version_token_hash=change.observed_version_token_hash,
        authorized_byte_size=change.observed_byte_size,
        authorized_mime_type_class=change.observed_mime_type_class,
        candidate_content_sha256=candidate.content_sha256,
        candidate_content_byte_count=candidate.content_byte_count,
        candidate_storage_object_key_hash=candidate.storage_object_key_hash,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="authorized",
        authorized_by_id=authorized_by_id,
        authorization_reason=normalized_reason,
        authorized_at=authorized_at,
        authorization_hash="",
        **_auth_safety(),
    )
    authorization.scope_hash = _auth_scope_hash(
        binding,
        candidate,
        change,
        current,
        prior_projection_hash=prior_projection_hash,
        prior_provider_version_hash=prior_provider_version_hash,
        request_key=normalized_key,
    )
    authorization.request_hash = _auth_request_hash(authorization)
    authorization.authorization_hash = _authorization_hash(authorization)
    db.add(authorization)
    db.flush()

    receipt = ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt(
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
        **_auth_safety(),
    )
    receipt.receipt_hash = _auth_receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    _ensure_authorization_integrity(db, authorization)
    db.commit()
    db.refresh(authorization)
    return authorization, "authorized"


def get_external_document_source_family_version_admission_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceFamilyVersionAdmissionAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionAuthorization).where(
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.id
            == authorization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.profile_id
            == profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError(
            "Later-version admission authorization not found"
        )
    _ensure_authorization_integrity(db, authorization)
    return authorization


def list_external_document_source_family_version_admission_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> list[ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt]:
    authorization = get_external_document_source_family_version_admission_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    return _auth_receipts(db, authorization)


def _authorization_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceFamilyVersionAdmissionAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionAuthorization)
        .where(
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.id
            == authorization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError(
            "Later-version admission authorization not found"
        )
    _ensure_authorization_integrity(db, authorization)
    return authorization


def _fresh_projection(
    db: Session,
    authorization: ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
):
    candidate = _candidate(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        candidate_id=authorization.successor_versioned_restaging_execution_id,
        for_update=False,
    )
    change = _successor_change(db, candidate)
    latest = _latest_successor_change(db, change)
    if latest is None or latest.id != change.id:
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization is stale because a newer source observation exists"
        )

    checkpoint = _checkpoint_generation(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        execution_id=change.checkpoint_generation_execution_id,
    )
    _base_candidate, _base_change, listing, _item, profile, policy, _baseline, _baseline_hash = (
        _successor_lineage(db, checkpoint)
    )
    adapter = _OBSERVATION_ADAPTERS.get(
        (profile.provider_kind, policy.observation_operation_kind)
    )
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "Exact-item metadata adapter is unavailable for later-version admission"
        )
    if (
        getattr(adapter, "provider_kind", None) != profile.provider_kind
        or getattr(adapter, "client_kind", None) != policy.client_kind
        or getattr(adapter, "observation_operation_kind", None)
        != policy.observation_operation_kind
        or getattr(adapter, "provider_origin", None) != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version metadata adapter policy drifted"
        )

    health_execution = _health_execution(db, listing)
    credential_binding = _active_binding(db, health_execution)
    locator = CredentialReferenceLocator(
        backend=credential_binding.reference_backend,
        namespace=credential_binding.reference_namespace,
        name=credential_binding.reference_name,
        version=credential_binding.reference_version,
    )
    try:
        result = adapter.read_item_metadata(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "Fresh exact-item metadata revalidation failed"
        ) from None
    projection = _validate_result(result)
    if projection is None:
        raise ExternalDocumentSourceConflictError(
            "Authorized external file is no longer present"
        )

    facts = {
        "provider_item_id_hash": hashlib.sha256(
            projection.provider_item_id.encode("utf-8")
        ).hexdigest(),
        "item_kind": projection.item_kind,
        "display_name_hash": hashlib.sha256(
            projection.display_name.encode("utf-8")
        ).hexdigest(),
        "parent_item_id_hash": (
            hashlib.sha256(projection.parent_item_id.encode("utf-8")).hexdigest()
            if projection.parent_item_id is not None
            else None
        ),
        "mime_type_class": projection.mime_type_class,
        "byte_size": projection.byte_size,
        "modified_at": projection.modified_at,
        "version_token_hash": projection.version_token_hash,
    }
    fresh_hash = _projection_hash(facts)
    if (
        facts["provider_item_id_hash"] != authorization.stable_source_item_hash
        or projection.item_kind != "file"
        or fresh_hash != authorization.authorized_projection_hash
        or facts["display_name_hash"] != authorization.authorized_display_name_hash
        or facts["version_token_hash"] != authorization.authorized_version_token_hash
        or facts["byte_size"] != authorization.authorized_byte_size
        or facts["mime_type_class"] != authorization.authorized_mime_type_class
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized external file changed after human authorization"
        )
    return candidate, projection, fresh_hash, facts


def _read_staged_payload(
    candidate: ExternalDocumentSourceSuccessorVersionedRestagingExecution,
) -> bytes:
    if (
        candidate.content_sha256 is None
        or candidate.content_byte_count is None
        or candidate.content_proof_hash is None
        or candidate.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized staged candidate proof is incomplete"
        )
    store = _configured_store()
    try:
        metadata = store.head_object(storage_key=candidate.storage_object_key)
        if (
            metadata.file_hash.lower() != candidate.content_sha256.lower()
            or metadata.file_size_bytes != candidate.content_byte_count
            or (
                candidate.stored_etag is not None
                and metadata.etag is not None
                and metadata.etag != candidate.stored_etag
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "Authorized staged candidate metadata drifted"
            )
        payload = store.get_bytes(
            storage_key=candidate.storage_object_key,
            expected_sha256=candidate.content_sha256,
        )
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise ExternalDocumentSourceConflictError(
            "Authorized staged candidate is missing"
        ) from None
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Authorized staged candidate integrity verification failed"
        ) from None
    if (
        len(payload) != candidate.content_byte_count
        or hashlib.sha256(payload).hexdigest() != candidate.content_sha256
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized staged candidate bytes drifted"
        )
    return payload


def _establish_next_document_version(
    db: Session,
    *,
    prior_document: Document,
    executed_by_id: UUID,
    executed_at: datetime,
    new_document_id: UUID,
    original_filename: str,
    mime_type: str,
    file_size_bytes: int,
    file_hash: str,
    storage_key: str,
    malware_scanned_at: datetime,
    replacement_reason: str,
) -> Document:
    if not prior_document.is_current or prior_document.deleted_at is not None:
        raise ExternalDocumentSourceConflictError(
            "Evidence family prior Document is no longer current"
        )

    prior_document.is_current = False
    prior_document.superseded_at = executed_at
    prior_document.superseded_by_id = executed_by_id
    db.flush()

    new_document = Document(
        id=new_document_id,
        organization_id=prior_document.organization_id,
        claim_id=prior_document.claim_id,
        uploaded_by_id=executed_by_id,
        supersedes_document_id=prior_document.id,
        document_family_id=prior_document.document_family_id,
        version_number=prior_document.version_number + 1,
        is_current=True,
        replacement_reason=replacement_reason,
        source_admission_note=replacement_reason[:1000],
        filename=original_filename,
        original_filename=original_filename,
        document_type=prior_document.document_type,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        file_hash=file_hash,
        storage_key=storage_key,
        confidentiality_level=prior_document.confidentiality_level,
        malware_scan_status=DocumentMalwareScanStatus.CLEAN,
        malware_scanned_at=malware_scanned_at,
    )
    db.add(new_document)
    db.flush()

    current_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.organization_id == prior_document.organization_id,
            Document.claim_id == prior_document.claim_id,
            Document.document_family_id == prior_document.document_family_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
        )
    )
    if current_count != 1:
        raise ExternalDocumentSourceConflictError(
            "Evidence family current-version invariant was not established"
        )
    return new_document


def _exec_scope_hash(
    authorization: ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
    *,
    prior_document: Document,
    new_document_id: UUID,
    new_version_number: int,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "binding_id": str(authorization.binding_id),
            "document_family_id": str(authorization.document_family_id),
            "prior_document_id": str(prior_document.id),
            "prior_version_number": prior_document.version_number,
            "new_document_id": str(new_document_id),
            "new_version_number": new_version_number,
            "request_key": request_key,
        }
    )


def _exec_request_hash(
    execution: ExternalDocumentSourceFamilyVersionAdmissionExecution,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "executed_by_id": str(execution.executed_by_id),
            "execution_reason": execution.execution_reason,
            "executed_at": _iso(execution.executed_at),
            **_exec_safety(),
        }
    )


def _exec_completion_hash(
    execution: ExternalDocumentSourceFamilyVersionAdmissionExecution,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "status": execution.status,
            "authorization_hash": execution.authorization_hash,
            "prior_document_id": str(execution.prior_document_id),
            "prior_version_number": execution.prior_version_number,
            "new_document_id": str(execution.new_document_id),
            "new_version_number": execution.new_version_number,
            "fresh_projection_hash": execution.fresh_projection_hash,
            "fresh_version_token_hash": execution.fresh_version_token_hash,
            "staged_content_sha256": execution.staged_content_sha256,
            "staged_content_byte_count": execution.staged_content_byte_count,
            "new_document_file_hash": execution.new_document_file_hash,
            "new_document_file_size_bytes": execution.new_document_file_size_bytes,
            "new_document_filename_hash": execution.new_document_filename_hash,
            "canonical_storage_key_hash": execution.canonical_storage_key_hash,
            **_exec_safety(),
        }
    )


def _exec_receipt_hash(
    receipt: ExternalDocumentSourceFamilyVersionAdmissionReceipt,
) -> str:
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
            **_exec_safety(),
        }
    )


def _exec_receipts(
    db: Session,
    execution: ExternalDocumentSourceFamilyVersionAdmissionExecution,
) -> list[ExternalDocumentSourceFamilyVersionAdmissionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceFamilyVersionAdmissionReceipt)
            .where(
                ExternalDocumentSourceFamilyVersionAdmissionReceipt.organization_id
                == execution.organization_id,
                ExternalDocumentSourceFamilyVersionAdmissionReceipt.execution_id
                == execution.id,
            )
            .order_by(
                ExternalDocumentSourceFamilyVersionAdmissionReceipt.sequence_number.asc()
            )
        ).all()
    )


def _ensure_execution_integrity(
    db: Session,
    execution: ExternalDocumentSourceFamilyVersionAdmissionExecution,
) -> None:
    authorization = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionAuthorization).where(
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.id
            == execution.authorization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.organization_id
            == execution.organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionAuthorization.profile_id
            == execution.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "Later-version execution authorization is missing"
        )
    _ensure_authorization_integrity(db, authorization)

    binding = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding).where(
            ExternalDocumentSourceEvidenceFamilyBinding.id == execution.binding_id,
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == execution.organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id
            == execution.profile_id,
        )
    )
    if binding is None:
        raise ExternalDocumentSourceConflictError(
            "Later-version execution family binding is missing"
        )
    _ensure_binding_integrity(db, binding)

    candidate = _candidate(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        candidate_id=execution.successor_versioned_restaging_execution_id,
        for_update=False,
    )
    change = _successor_change(db, candidate)
    prior = db.get(Document, execution.prior_document_id)
    new = db.get(Document, execution.new_document_id)
    if prior is None or new is None:
        raise ExternalDocumentSourceConflictError(
            "Later-version execution Document lineage is missing"
        )

    expected = {
        "claim_id": authorization.claim_id,
        "binding_id": authorization.binding_id,
        "successor_change_detection_execution_id":
            authorization.successor_change_detection_execution_id,
        "successor_versioned_restaging_execution_id":
            authorization.successor_versioned_restaging_execution_id,
        "document_family_id": authorization.document_family_id,
        "provider_kind": authorization.provider_kind,
        "profile_hash": authorization.profile_hash,
        "stable_source_item_hash": authorization.stable_source_item_hash,
        "authorization_hash": authorization.authorization_hash,
        "successor_change_completion_hash":
            authorization.successor_change_completion_hash,
        "candidate_content_proof_hash":
            authorization.candidate_content_proof_hash,
        "candidate_completion_hash": authorization.candidate_completion_hash,
        "prior_projection_hash": authorization.prior_projection_hash,
        "prior_provider_version_hash":
            authorization.prior_provider_version_hash,
        "prior_document_file_hash": prior.file_hash,
        "fresh_projection_hash": authorization.authorized_projection_hash,
        "fresh_display_name_hash": authorization.authorized_display_name_hash,
        "fresh_version_token_hash":
            authorization.authorized_version_token_hash,
        "fresh_byte_size": authorization.authorized_byte_size,
        "fresh_mime_type_class": authorization.authorized_mime_type_class,
        "staged_content_sha256": candidate.content_sha256,
        "staged_content_byte_count": candidate.content_byte_count,
        "staged_storage_object_key_hash": candidate.storage_object_key_hash,
        "new_document_file_hash": new.file_hash,
        "new_document_file_size_bytes": new.file_size_bytes,
        "status": "admitted",
    }
    for field, value in expected.items():
        if getattr(execution, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Later-version execution integrity drifted at {field}"
            )

    if (
        prior.organization_id != execution.organization_id
        or prior.claim_id != execution.claim_id
        or prior.document_family_id != execution.document_family_id
        or prior.version_number != execution.prior_version_number
        or prior.file_hash != execution.prior_document_file_hash
        or new.organization_id != execution.organization_id
        or new.claim_id != execution.claim_id
        or new.document_family_id != execution.document_family_id
        or new.version_number != execution.new_version_number
        or new.version_number != prior.version_number + 1
        or new.supersedes_document_id != prior.id
        or new.uploaded_by_id != execution.executed_by_id
        or new.replacement_reason != execution.execution_reason
        or new.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or execution.new_document_filename_hash
        != hashlib.sha256(new.original_filename.encode("utf-8")).hexdigest()
        or execution.canonical_storage_key_hash
        != hashlib.sha256(new.storage_key.encode("utf-8")).hexdigest()
        or change.observed_provider_item_id_hash
        != execution.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version execution canonical lineage drifted"
        )

    expected_scope = _exec_scope_hash(
        authorization,
        prior_document=prior,
        new_document_id=new.id,
        new_version_number=new.version_number,
        request_key=execution.request_key,
    )
    if (
        execution.scope_hash != expected_scope
        or execution.request_hash != _exec_request_hash(execution)
        or execution.completion_hash != _exec_completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version execution cryptographic integrity failed"
        )
    for field, value in _exec_safety().items():
        if bool(getattr(execution, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Later-version execution safety boundary drifted"
            )

    receipts = _exec_receipts(db, execution)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Later-version execution receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "admitted"
        or receipt.status_after != "admitted"
        or receipt.actor_id != execution.executed_by_id
        or _aware(receipt.occurred_at) != _aware(execution.executed_at)
        or receipt.reason != execution.execution_reason
        or receipt.scope_hash != execution.scope_hash
        or receipt.decision_hash != execution.completion_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _exec_receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version execution receipt integrity drifted"
        )
    for field, value in _exec_safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Later-version execution receipt safety boundary drifted"
            )


def _cleanup_local_storage(
    *,
    local_storage,
    promoted: bool,
    temp_exists: bool,
    canonical_key: str,
    quarantine_key: str,
) -> None:
    try:
        if promoted:
            local_storage.delete_physical(canonical_key)
        elif temp_exists:
            local_storage.delete_physical(quarantine_key)
    except (StorageError, OSError):
        pass


def execute_external_document_source_family_version_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    authorization_id: UUID,
    executed_by_id: UUID,
    request_key: str,
    execution_reason: str,
) -> tuple[ExternalDocumentSourceFamilyVersionAdmissionExecution, str]:
    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        execution_reason,
        field="reason",
        minimum=20,
        maximum=2000,
    )

    authorization = _authorization_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    if authorization.binding_id != binding_id:
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization belongs to a different Evidence family"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionExecution).where(
            ExternalDocumentSourceFamilyVersionAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.authorization_id
            == authorization.id,
        )
    )
    if existing is not None:
        _ensure_execution_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.execution_reason != normalized_reason
            or existing.executed_by_id != executed_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Authorization was already consumed by a different admission execution"
            )
        return existing, "replayed"

    collision = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionExecution).where(
            ExternalDocumentSourceFamilyVersionAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.profile_id
            == profile_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "request_key is already bound to another later-version admission"
        )

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    current = _lock_current_family_document(
        db,
        organization_id=organization_id,
        claim_id=binding.claim_id,
        document_family_id=binding.document_family_id,
        expected_current_document_id=authorization.expected_prior_document_id,
    )
    if (
        current.version_number != authorization.expected_prior_version_number
        or current.file_hash != authorization.prior_document_file_hash
        or binding.claim_id != authorization.claim_id
        or binding.document_family_id != authorization.document_family_id
        or binding.stable_source_item_hash != authorization.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization is stale against the canonical Evidence family"
        )

    candidate, projection, fresh_hash, fresh_facts = _fresh_projection(
        db,
        authorization,
    )
    payload = _read_staged_payload(candidate)
    if len(payload) == 0:
        raise ExternalDocumentSourceConflictError(
            "Empty external files cannot be admitted as Evidence"
        )
    if len(payload) > settings.max_upload_bytes:
        raise ExternalDocumentSourceConflictError(
            "Authorized staged file exceeds the configured Evidence upload limit"
        )
    if (
        len(payload) != authorization.candidate_content_byte_count
        or hashlib.sha256(payload).hexdigest()
        != authorization.candidate_content_sha256
        or authorization.candidate_content_sha256 == current.file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized staged bytes no longer represent a distinct later version"
        )

    duplicate = db.scalar(
        select(Document.id).where(
            Document.organization_id == organization_id,
            Document.claim_id == binding.claim_id,
            Document.file_hash == authorization.candidate_content_sha256,
            Document.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ExternalDocumentSourceConflictError(
            "These bytes already exist in the Claim Evidence record"
        )
    if not settings.malware_scan_enabled:
        raise ExternalDocumentSourceConflictError(
            "Later-version admission is blocked because authoritative malware scanning is disabled"
        )

    original_filename = normalize_original_filename(projection.display_name)
    try:
        suffix = validate_upload(
            original_filename,
            projection.mime_type_class,
        )
    except HTTPException as exc:
        raise ExternalDocumentSourceConflictError(
            "Authorized external file type is not supported for Evidence admission"
        ) from exc
    mime_type = (projection.mime_type_class or "application/octet-stream")[:150]

    local_storage = _storage()
    quarantine_key = make_quarantine_key(
        organization_id=organization_id,
        claim_id=binding.claim_id,
        upload_id=uuid4(),
        suffix=suffix,
    )
    new_document_id = uuid4()
    canonical_key = make_storage_key(
        organization_id=organization_id,
        claim_id=binding.claim_id,
        document_id=new_document_id,
        suffix=suffix,
    )
    promoted = False
    temp_exists = False
    committed = False
    try:
        stored = local_storage.save_bytes(payload, quarantine_key)
        temp_exists = True
        if (
            stored.file_hash != authorization.candidate_content_sha256
            or stored.file_size_bytes != authorization.candidate_content_byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Local Evidence quarantine copy failed integrity verification"
            )
        try:
            validate_file_signature(local_storage, quarantine_key, suffix)
        except HTTPException as exc:
            temp_exists = False
            raise ExternalDocumentSourceConflictError(
                "Authorized external bytes do not match the declared file type"
            ) from exc

        scanned_at = _utc_now()
        try:
            scan_result = scan_file(
                local_storage.path_for(quarantine_key),
                host=settings.clamav_host,
                port=settings.clamav_port,
                timeout_seconds=settings.clamav_timeout_seconds,
            )
        except MalwareScannerError as exc:
            raise ExternalDocumentSourceConflictError(
                "Admission-time malware scanning could not return an authoritative verdict"
            ) from exc
        if scan_result.verdict != MalwareScanVerdict.CLEAN:
            raise ExternalDocumentSourceConflictError(
                "Malware was detected during later external Evidence admission"
            )

        local_storage.promote(quarantine_key, canonical_key)
        temp_exists = False
        promoted = True

        executed_at = _utc_now()
        new_document = _establish_next_document_version(
            db,
            prior_document=current,
            executed_by_id=executed_by_id,
            executed_at=executed_at,
            new_document_id=new_document_id,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            storage_key=canonical_key,
            malware_scanned_at=scanned_at,
            replacement_reason=normalized_reason,
        )

        execution = ExternalDocumentSourceFamilyVersionAdmissionExecution(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=binding.claim_id,
            profile_id=profile_id,
            binding_id=binding.id,
            authorization_id=authorization.id,
            successor_change_detection_execution_id=
                authorization.successor_change_detection_execution_id,
            successor_versioned_restaging_execution_id=
                authorization.successor_versioned_restaging_execution_id,
            document_family_id=binding.document_family_id,
            prior_document_id=current.id,
            prior_version_number=current.version_number,
            new_document_id=new_document.id,
            new_version_number=new_document.version_number,
            provider_kind=binding.provider_kind,
            profile_hash=binding.profile_hash,
            stable_source_item_hash=binding.stable_source_item_hash,
            authorization_hash=authorization.authorization_hash,
            successor_change_completion_hash=
                authorization.successor_change_completion_hash,
            candidate_content_proof_hash=
                authorization.candidate_content_proof_hash,
            candidate_completion_hash=authorization.candidate_completion_hash,
            prior_projection_hash=authorization.prior_projection_hash,
            prior_provider_version_hash=
                authorization.prior_provider_version_hash,
            prior_document_file_hash=current.file_hash,
            fresh_projection_hash=fresh_hash,
            fresh_display_name_hash=fresh_facts["display_name_hash"],
            fresh_version_token_hash=fresh_facts["version_token_hash"],
            fresh_byte_size=len(payload),
            fresh_mime_type_class=fresh_facts["mime_type_class"],
            staged_content_sha256=candidate.content_sha256,
            staged_content_byte_count=candidate.content_byte_count,
            staged_storage_object_key_hash=candidate.storage_object_key_hash,
            new_document_file_hash=new_document.file_hash,
            new_document_file_size_bytes=new_document.file_size_bytes,
            new_document_filename_hash=hashlib.sha256(
                original_filename.encode("utf-8")
            ).hexdigest(),
            canonical_storage_key_hash=hashlib.sha256(
                canonical_key.encode("utf-8")
            ).hexdigest(),
            request_key=normalized_key,
            scope_hash="",
            request_hash="",
            status="admitted",
            executed_by_id=executed_by_id,
            execution_reason=normalized_reason,
            executed_at=executed_at,
            completion_hash="",
            **_exec_safety(),
        )
        execution.scope_hash = _exec_scope_hash(
            authorization,
            prior_document=current,
            new_document_id=new_document.id,
            new_version_number=new_document.version_number,
            request_key=normalized_key,
        )
        execution.request_hash = _exec_request_hash(execution)
        execution.completion_hash = _exec_completion_hash(execution)
        db.add(execution)
        db.flush()

        receipt = ExternalDocumentSourceFamilyVersionAdmissionReceipt(
            id=uuid4(),
            organization_id=organization_id,
            execution_id=execution.id,
            sequence_number=1,
            event_type="admitted",
            status_after="admitted",
            actor_id=executed_by_id,
            occurred_at=executed_at,
            reason=normalized_reason,
            scope_hash=execution.scope_hash,
            decision_hash=execution.completion_hash,
            prior_receipt_hash=None,
            receipt_hash="",
            **_exec_safety(),
        )
        receipt.receipt_hash = _exec_receipt_hash(receipt)
        db.add(receipt)
        db.flush()
        _ensure_execution_integrity(db, execution)

        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=executed_by_id,
            action="ADMIT_LATER_EXTERNAL_EVIDENCE_VERSION",
            entity_type="document",
            entity_id=new_document.id,
            new_values={
                "claim_id": str(binding.claim_id),
                "evidence_family_binding_id": str(binding.id),
                "family_version_authorization_id": str(authorization.id),
                "family_version_admission_execution_id": str(execution.id),
                "document_family_id": str(binding.document_family_id),
                "prior_document_id": str(current.id),
                "prior_version_number": current.version_number,
                "new_document_id": str(new_document.id),
                "new_version_number": new_document.version_number,
                "stable_source_item_hash": binding.stable_source_item_hash,
                "file_hash": new_document.file_hash,
                "file_size_bytes": new_document.file_size_bytes,
                "malware_scan_status": new_document.malware_scan_status.value,
                "processing_enqueued": False,
                "ai_executed": False,
            },
            details=(
                "A separately human-authorized Phase-T staged source version was "
                "revalidated against fresh exact remote metadata, verified from "
                "governed staged bytes, malware-scanned, and admitted as the next "
                "immutable canonical Document version. No processing, AI, Claim "
                "mutation, checkpoint advancement or background synchronization was started."
            ),
        )
        db.commit()
        committed = True
        db.refresh(execution)
        return execution, "admitted"
    except SQLAlchemyError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "Later-version admission was committed but response finalization failed; replay the same request key"
            ) from exc
        db.rollback()
        _cleanup_local_storage(
            local_storage=local_storage,
            promoted=promoted,
            temp_exists=temp_exists,
            canonical_key=canonical_key,
            quarantine_key=quarantine_key,
        )
        raise ExternalDocumentSourceConflictError(
            "Later-version Evidence admission could not be committed safely"
        ) from exc
    except StorageError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "Later-version admission was committed but local response finalization failed; replay the same request key"
            ) from exc
        db.rollback()
        _cleanup_local_storage(
            local_storage=local_storage,
            promoted=promoted,
            temp_exists=temp_exists,
            canonical_key=canonical_key,
            quarantine_key=quarantine_key,
        )
        raise ExternalDocumentSourceConflictError(
            "Local Evidence storage operation failed"
        ) from exc
    except Exception:
        if committed:
            raise
        db.rollback()
        _cleanup_local_storage(
            local_storage=local_storage,
            promoted=promoted,
            temp_exists=temp_exists,
            canonical_key=canonical_key,
            quarantine_key=quarantine_key,
        )
        raise
    finally:
        del payload


def get_external_document_source_family_version_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceFamilyVersionAdmissionExecution:
    execution = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionExecution).where(
            ExternalDocumentSourceFamilyVersionAdmissionExecution.id == execution_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.profile_id
            == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError(
            "Family-version admission execution not found"
        )
    _ensure_execution_integrity(db, execution)
    return execution


def list_external_document_source_family_version_admission_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> list[ExternalDocumentSourceFamilyVersionAdmissionReceipt]:
    execution = get_external_document_source_family_version_admission(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _exec_receipts(db, execution)
