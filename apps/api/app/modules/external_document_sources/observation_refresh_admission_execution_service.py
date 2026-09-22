from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
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
from app.modules.external_document_sources.family_version_admission_service import (
    _binding_for_update,
    _cleanup_local_storage,
    _establish_next_document_version,
    _lock_current_family_document,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    ensure_observation_refresh_admission_authorization_integrity,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
    ExternalDocumentSourceObservationRefreshAdmissionReceipt,
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
from app.modules.external_document_sources.remote_content_staging_service import (
    _configured_store,
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
        "authorization_verified": True,
        "refresh_execution_verified": True,
        "durable_family_binding_verified": True,
        "stable_source_identity_verified": True,
        "authorization_single_use_consumed": True,
        "current_document_verified": True,
        "staged_storage_read_performed": True,
        "staged_content_integrity_verified": True,
        "file_signature_validated": True,
        "malware_scan_completed": True,
        "canonical_document_write_completed": True,
        "new_document_created": True,
        "prior_document_superseded": True,
        "exactly_one_current_version_established": True,
        "refreshed_version_admitted": True,
        "provider_client_constructed": False,
        "oauth_token_acquired": False,
        "remote_list_performed": False,
        "remote_metadata_read_performed": False,
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


def _authorization_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceObservationRefreshAdmissionAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionAuthorization)
        .where(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.id
            == authorization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.profile_id
            == profile_id,
        )
        .with_for_update()
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


def _execution_scope_hash(
    authorization: ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
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
            "refresh_execution_id": str(authorization.refresh_execution_id),
            "binding_id": str(authorization.binding_id),
            "document_family_id": str(authorization.document_family_id),
            "prior_document_id": str(prior_document.id),
            "prior_version_number": prior_document.version_number,
            "new_document_id": str(new_document_id),
            "new_version_number": new_version_number,
            "request_key": request_key,
        }
    )


def _execution_request_hash(
    execution: ExternalDocumentSourceObservationRefreshAdmissionExecution,
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


def _security_verification_hash(
    *,
    content_sha256: str,
    content_byte_count: int,
    mime_type: str,
    suffix: str,
    malware_scan_verdict: str,
    malware_scanned_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "content_sha256": content_sha256,
            "content_byte_count": content_byte_count,
            "mime_type": mime_type,
            "validated_file_suffix": suffix,
            "malware_scan_verdict": malware_scan_verdict,
            "malware_scanned_at": _iso(malware_scanned_at),
        }
    )


def _execution_completion_hash(
    execution: ExternalDocumentSourceObservationRefreshAdmissionExecution,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "status": execution.status,
            "authorization_hash": execution.authorization_hash,
            "refresh_completion_hash": execution.refresh_completion_hash,
            "prior_document_id": str(execution.prior_document_id),
            "prior_version_number": execution.prior_version_number,
            "new_document_id": str(execution.new_document_id),
            "new_version_number": execution.new_version_number,
            "refreshed_content_proof_hash": execution.refreshed_content_proof_hash,
            "refreshed_content_sha256": execution.refreshed_content_sha256,
            "refreshed_content_byte_count": execution.refreshed_content_byte_count,
            "staged_storage_object_key_hash": execution.staged_storage_object_key_hash,
            "validated_file_suffix": execution.validated_file_suffix,
            "malware_scan_verdict": execution.malware_scan_verdict,
            "security_verification_hash": execution.security_verification_hash,
            "new_document_file_hash": execution.new_document_file_hash,
            "new_document_file_size_bytes": execution.new_document_file_size_bytes,
            "new_document_filename_hash": execution.new_document_filename_hash,
            "canonical_storage_key_hash": execution.canonical_storage_key_hash,
            **_safety(),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceObservationRefreshAdmissionReceipt,
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
            **_safety(),
        }
    )


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceObservationRefreshAdmissionExecution,
) -> list[ExternalDocumentSourceObservationRefreshAdmissionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshAdmissionReceipt)
            .where(
                ExternalDocumentSourceObservationRefreshAdmissionReceipt.organization_id
                == execution.organization_id,
                ExternalDocumentSourceObservationRefreshAdmissionReceipt.execution_id
                == execution.id,
            )
            .order_by(
                ExternalDocumentSourceObservationRefreshAdmissionReceipt.sequence_number.asc()
            )
        ).all()
    )


def _refresh_from_authorization(
    db: Session,
    authorization: ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
) -> ExternalDocumentSourceObservationRefreshExecution:
    refresh = db.get(
        ExternalDocumentSourceObservationRefreshExecution,
        authorization.refresh_execution_id,
    )
    if refresh is None:
        raise ExternalDocumentSourceConflictError(
            "Authorized observation refresh execution is missing"
        )
    ensure_observation_refresh_execution_integrity(
        db,
        refresh,
        verify_storage=False,
    )
    if (
        refresh.organization_id != authorization.organization_id
        or refresh.claim_id != authorization.claim_id
        or refresh.profile_id != authorization.profile_id
        or refresh.binding_id != authorization.binding_id
        or refresh.document_family_id != authorization.document_family_id
        or refresh.completion_hash != authorization.refresh_completion_hash
        or refresh.content_proof_hash != authorization.refreshed_content_proof_hash
        or refresh.content_sha256 != authorization.refreshed_content_sha256
        or refresh.content_byte_count != authorization.refreshed_content_byte_count
        or refresh.content_media_type_class
        != authorization.refreshed_content_media_type_class
        or refresh.content_version_token_hash
        != authorization.refreshed_content_version_token_hash
        or refresh.storage_backend_kind != authorization.storage_backend_kind
        or refresh.storage_purpose != authorization.storage_purpose
        or refresh.storage_object_key_hash != authorization.storage_object_key_hash
        or hashlib.sha256(refresh.storage_object_key.encode("utf-8")).hexdigest()
        != authorization.storage_object_key_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized observation refresh staged-content lineage drifted"
        )
    return refresh


def _read_authorized_staged_payload(
    refresh: ExternalDocumentSourceObservationRefreshExecution,
    authorization: ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
) -> bytes:
    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if backend != authorization.storage_backend_kind:
        raise ExternalDocumentSourceConflictError(
            "Authorized observation refresh storage backend identity drifted"
        )
    try:
        metadata = store.head_object(storage_key=refresh.storage_object_key)
        if (
            metadata.file_hash.lower()
            != authorization.refreshed_content_sha256.lower()
            or metadata.file_size_bytes
            != authorization.refreshed_content_byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Authorized observation refresh staged object metadata drifted"
            )
        payload = store.get_bytes(
            storage_key=refresh.storage_object_key,
            expected_sha256=authorization.refreshed_content_sha256,
        )
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise ExternalDocumentSourceConflictError(
            "Authorized observation refresh staged object is missing"
        ) from None
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Authorized observation refresh staged object integrity verification failed"
        ) from None

    if (
        len(payload) != authorization.refreshed_content_byte_count
        or hashlib.sha256(payload).hexdigest()
        != authorization.refreshed_content_sha256
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized observation refresh staged bytes drifted"
        )
    return payload


def _canonical_filename(
    prior_document: Document,
    media_type: str | None,
) -> tuple[str, str, str]:
    original = normalize_original_filename(
        prior_document.original_filename or prior_document.filename
    )
    current_suffix = Path(original).suffix.lower()
    effective_media = (
        media_type
        or prior_document.mime_type
        or "application/octet-stream"
    ).lower()

    preferred_suffix = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }.get(effective_media)

    if preferred_suffix is not None:
        if effective_media == "image/jpeg" and current_suffix in {".jpg", ".jpeg"}:
            suffix = current_suffix
        else:
            suffix = preferred_suffix
        stem = Path(original).stem.strip() or "document"
        original = normalize_original_filename(f"{stem}{suffix}")

    try:
        suffix = validate_upload(original, effective_media)
    except HTTPException as exc:
        raise ExternalDocumentSourceConflictError(
            "Authorized refreshed file type is not supported for Evidence admission"
        ) from exc
    return original, suffix, effective_media[:150]


def ensure_observation_refresh_admission_execution_integrity(
    db: Session,
    execution: ExternalDocumentSourceObservationRefreshAdmissionExecution,
) -> None:
    authorization = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionAuthorization).where(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.id
            == execution.authorization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.organization_id
            == execution.organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization.profile_id
            == execution.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission execution authorization is missing"
        )
    ensure_observation_refresh_admission_authorization_integrity(
        db,
        authorization,
    )
    refresh = _refresh_from_authorization(db, authorization)

    binding = _binding_for_update(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        binding_id=execution.binding_id,
    )
    prior = db.get(Document, execution.prior_document_id)
    new = db.get(Document, execution.new_document_id)
    if prior is None or new is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission Document lineage is missing"
        )

    expected = {
        "claim_id": authorization.claim_id,
        "binding_id": authorization.binding_id,
        "refresh_execution_id": authorization.refresh_execution_id,
        "document_family_id": authorization.document_family_id,
        "provider_kind": authorization.provider_kind,
        "profile_hash": authorization.profile_hash,
        "stable_source_item_hash": authorization.stable_source_item_hash,
        "authorization_hash": authorization.authorization_hash,
        "refresh_completion_hash": authorization.refresh_completion_hash,
        "binding_completion_hash": authorization.binding_completion_hash,
        "prior_document_file_hash": authorization.prior_document_file_hash,
        "refreshed_content_proof_hash": authorization.refreshed_content_proof_hash,
        "refreshed_content_sha256": authorization.refreshed_content_sha256,
        "refreshed_content_byte_count": authorization.refreshed_content_byte_count,
        "refreshed_content_media_type_class":
            authorization.refreshed_content_media_type_class,
        "refreshed_content_version_token_hash":
            authorization.refreshed_content_version_token_hash,
        "staged_storage_backend_kind": authorization.storage_backend_kind,
        "staged_storage_purpose": authorization.storage_purpose,
        "staged_storage_object_key_hash": authorization.storage_object_key_hash,
        "new_document_file_hash": new.file_hash,
        "new_document_file_size_bytes": new.file_size_bytes,
        "malware_scan_verdict": "clean",
        "status": "admitted",
    }
    for field, value in expected.items():
        if getattr(execution, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Observation refresh admission execution drifted at {field}"
            )

    if (
        refresh.id != execution.refresh_execution_id
        or binding.claim_id != execution.claim_id
        or binding.document_family_id != execution.document_family_id
        or binding.provider_kind != execution.provider_kind
        or binding.profile_hash != execution.profile_hash
        or binding.stable_source_item_hash != execution.stable_source_item_hash
        or binding.completion_hash != execution.binding_completion_hash
        or prior.organization_id != execution.organization_id
        or prior.claim_id != execution.claim_id
        or prior.document_family_id != execution.document_family_id
        or prior.version_number != execution.prior_version_number
        or prior.file_hash != execution.prior_document_file_hash
        or prior.superseded_by_id != execution.executed_by_id
        or new.organization_id != execution.organization_id
        or new.claim_id != execution.claim_id
        or new.document_family_id != execution.document_family_id
        or new.version_number != execution.new_version_number
        or new.version_number != prior.version_number + 1
        or new.supersedes_document_id != prior.id
        or new.uploaded_by_id != execution.executed_by_id
        or new.replacement_reason != execution.execution_reason
        or new.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or new.malware_scanned_at is None
        or execution.new_document_filename_hash
        != hashlib.sha256(new.original_filename.encode("utf-8")).hexdigest()
        or execution.canonical_storage_key_hash
        != hashlib.sha256(new.storage_key.encode("utf-8")).hexdigest()
        or execution.security_verification_hash
        != _security_verification_hash(
            content_sha256=execution.refreshed_content_sha256,
            content_byte_count=execution.refreshed_content_byte_count,
            mime_type=new.mime_type,
            suffix=execution.validated_file_suffix,
            malware_scan_verdict=execution.malware_scan_verdict,
            malware_scanned_at=new.malware_scanned_at,
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission canonical lineage drifted"
        )

    expected_scope = _execution_scope_hash(
        authorization,
        prior_document=prior,
        new_document_id=new.id,
        new_version_number=new.version_number,
        request_key=execution.request_key,
    )
    if (
        execution.scope_hash != expected_scope
        or execution.request_hash != _execution_request_hash(execution)
        or execution.completion_hash != _execution_completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission execution cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(execution, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission execution safety boundary drifted"
            )

    receipts = _receipts(db, execution)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission receipt lifecycle drifted"
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
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission receipt safety boundary drifted"
            )


def execute_observation_refresh_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    authorization_id: UUID,
    executed_by_id: UUID,
    request_key: str,
    execution_reason: str,
) -> tuple[ExternalDocumentSourceObservationRefreshAdmissionExecution, str]:
    _require_human_admin(
        db,
        organization_id=organization_id,
        user_id=executed_by_id,
    )
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
            "Observation refresh admission authorization belongs to a different Evidence family"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionExecution).where(
            ExternalDocumentSourceObservationRefreshAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.authorization_id
            == authorization.id,
        )
    )
    if existing is not None:
        ensure_observation_refresh_admission_execution_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.execution_reason != normalized_reason
            or existing.executed_by_id != executed_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission authorization was already consumed by a different execution"
            )
        return existing, "replayed"

    collision = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionExecution).where(
            ExternalDocumentSourceObservationRefreshAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.profile_id
            == profile_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "request_key is already bound to another observation refresh admission"
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
        or profile.provider_kind != authorization.provider_kind
        or profile.profile_hash != authorization.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission source profile authority drifted"
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
        claim_id=authorization.claim_id,
        document_family_id=authorization.document_family_id,
        expected_current_document_id=authorization.expected_prior_document_id,
    )
    if (
        binding.status != "active"
        or binding.claim_id != authorization.claim_id
        or binding.document_family_id != authorization.document_family_id
        or binding.provider_kind != authorization.provider_kind
        or binding.profile_hash != authorization.profile_hash
        or binding.stable_source_item_hash != authorization.stable_source_item_hash
        or binding.completion_hash != authorization.binding_completion_hash
        or current.version_number != authorization.expected_prior_version_number
        or current.file_hash != authorization.prior_document_file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission authorization is stale against canonical Evidence"
        )

    duplicate = db.scalar(
        select(Document.id).where(
            Document.organization_id == organization_id,
            Document.claim_id == authorization.claim_id,
            Document.file_hash == authorization.refreshed_content_sha256,
            Document.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ExternalDocumentSourceConflictError(
            "Authorized refreshed bytes already exist in Claim Evidence"
        )

    refresh = _refresh_from_authorization(db, authorization)
    payload: bytes | None = _read_authorized_staged_payload(
        refresh,
        authorization,
    )
    if len(payload) == 0:
        raise ExternalDocumentSourceConflictError(
            "Empty refreshed files cannot be admitted as Evidence"
        )
    if len(payload) > settings.max_upload_bytes:
        raise ExternalDocumentSourceConflictError(
            "Authorized refreshed file exceeds the configured Evidence upload limit"
        )
    if (
        len(payload) != authorization.refreshed_content_byte_count
        or hashlib.sha256(payload).hexdigest()
        != authorization.refreshed_content_sha256
        or authorization.refreshed_content_sha256 == current.file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized refreshed bytes no longer represent a distinct canonical version"
        )
    if not settings.malware_scan_enabled:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh admission is blocked because authoritative malware scanning is disabled"
        )

    original_filename, suffix, mime_type = _canonical_filename(
        current,
        authorization.refreshed_content_media_type_class,
    )
    local_storage = _storage()
    quarantine_key = make_quarantine_key(
        organization_id=organization_id,
        claim_id=authorization.claim_id,
        upload_id=uuid4(),
        suffix=suffix,
    )
    new_document_id = uuid4()
    canonical_key = make_storage_key(
        organization_id=organization_id,
        claim_id=authorization.claim_id,
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
            stored.file_hash != authorization.refreshed_content_sha256
            or stored.file_size_bytes != authorization.refreshed_content_byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Canonical Evidence quarantine copy failed integrity verification"
            )

        try:
            validate_file_signature(local_storage, quarantine_key, suffix)
        except HTTPException as exc:
            raise ExternalDocumentSourceConflictError(
                "Authorized refreshed bytes do not match the validated file type"
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
                "Malware was detected during observation refresh Evidence admission"
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
        security_hash = _security_verification_hash(
            content_sha256=authorization.refreshed_content_sha256,
            content_byte_count=authorization.refreshed_content_byte_count,
            mime_type=mime_type,
            suffix=suffix,
            malware_scan_verdict="clean",
            malware_scanned_at=scanned_at,
        )

        execution = ExternalDocumentSourceObservationRefreshAdmissionExecution(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=authorization.claim_id,
            profile_id=profile_id,
            binding_id=binding.id,
            authorization_id=authorization.id,
            refresh_execution_id=refresh.id,
            document_family_id=authorization.document_family_id,
            prior_document_id=current.id,
            prior_version_number=current.version_number,
            new_document_id=new_document.id,
            new_version_number=new_document.version_number,
            provider_kind=authorization.provider_kind,
            profile_hash=authorization.profile_hash,
            stable_source_item_hash=authorization.stable_source_item_hash,
            authorization_hash=authorization.authorization_hash,
            refresh_completion_hash=authorization.refresh_completion_hash,
            binding_completion_hash=authorization.binding_completion_hash,
            prior_document_file_hash=current.file_hash,
            refreshed_content_proof_hash=authorization.refreshed_content_proof_hash,
            refreshed_content_sha256=authorization.refreshed_content_sha256,
            refreshed_content_byte_count=authorization.refreshed_content_byte_count,
            refreshed_content_media_type_class=
                authorization.refreshed_content_media_type_class,
            refreshed_content_version_token_hash=
                authorization.refreshed_content_version_token_hash,
            staged_storage_backend_kind=authorization.storage_backend_kind,
            staged_storage_purpose=authorization.storage_purpose,
            staged_storage_object_key_hash=authorization.storage_object_key_hash,
            validated_file_suffix=suffix,
            malware_scan_verdict="clean",
            security_verification_hash=security_hash,
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
            **_safety(),
        )
        execution.scope_hash = _execution_scope_hash(
            authorization,
            prior_document=current,
            new_document_id=new_document.id,
            new_version_number=new_document.version_number,
            request_key=normalized_key,
        )
        execution.request_hash = _execution_request_hash(execution)
        execution.completion_hash = _execution_completion_hash(execution)
        db.add(execution)
        db.flush()

        receipt = ExternalDocumentSourceObservationRefreshAdmissionReceipt(
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
            **_safety(),
        )
        receipt.receipt_hash = _receipt_hash(receipt)
        db.add(receipt)
        db.flush()
        ensure_observation_refresh_admission_execution_integrity(
            db,
            execution,
        )

        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=executed_by_id,
            action="ADMIT_VERIFIED_OBSERVATION_REFRESH_AS_EVIDENCE_VERSION",
            entity_type="document",
            entity_id=new_document.id,
            new_values={
                "claim_id": str(authorization.claim_id),
                "evidence_family_binding_id": str(binding.id),
                "refresh_admission_authorization_id": str(authorization.id),
                "observation_refresh_execution_id": str(refresh.id),
                "refresh_admission_execution_id": str(execution.id),
                "document_family_id": str(authorization.document_family_id),
                "prior_document_id": str(current.id),
                "prior_version_number": current.version_number,
                "new_document_id": str(new_document.id),
                "new_version_number": new_document.version_number,
                "stable_source_item_hash": authorization.stable_source_item_hash,
                "file_hash": new_document.file_hash,
                "file_size_bytes": new_document.file_size_bytes,
                "malware_scan_status": new_document.malware_scan_status.value,
                "provider_io_performed": False,
                "processing_enqueued": False,
                "ai_executed": False,
                "checkpoint_advanced": False,
            },
            details=(
                "One exact Phase-AI-authorized AH staged refresh was read from "
                "governed quarantine, content-integrity checked, file-signature "
                "validated, freshly malware-scanned, and admitted as canonical "
                "Document N+1. No provider I/O, processing, external AI, Claim "
                "mutation, checkpoint advancement or background sync was performed."
            ),
        )
        db.commit()
        committed = True
        db.refresh(execution)
        return execution, "admitted"
    except SQLAlchemyError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission was committed but response finalization failed; replay the same request key"
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
            "Observation refresh Evidence admission could not be committed safely"
        ) from exc
    except StorageError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh admission was committed but local response finalization failed; replay the same request key"
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
        if payload is not None:
            del payload


def get_observation_refresh_admission_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceObservationRefreshAdmissionExecution:
    execution = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAdmissionExecution).where(
            ExternalDocumentSourceObservationRefreshAdmissionExecution.id
            == execution_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshAdmissionExecution.profile_id
            == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation refresh admission execution not found"
        )
    ensure_observation_refresh_admission_execution_integrity(db, execution)
    return execution


def list_observation_refresh_admission_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> list[ExternalDocumentSourceObservationRefreshAdmissionReceipt]:
    execution = get_observation_refresh_admission_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
