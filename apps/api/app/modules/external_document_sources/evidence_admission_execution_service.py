from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.malware import MalwareScannerError, MalwareScanVerdict, scan_file
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
)
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
from app.modules.external_document_sources.change_detection_service import (
    _OBSERVATION_ADAPTERS,
    _projection_hash,
    _validate_result,
)
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.evidence_admission_authorization_service import (
    _active_claim,
    _ensure_integrity as _ensure_authorization_integrity,
    _latest_completed_observation,
)
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
    ExternalDocumentSourceEvidenceAdmissionExecutionReceipt,
)
from app.modules.external_document_sources.generation_3_change_detection_service import (
    _checkpoint_generation_3,
    _lineage,
    get_external_document_source_generation_3_change_detection,
)
from app.modules.external_document_sources.remote_content_staging_service import _configured_store
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
        "upstream_authorization_verified": True,
        "authorization_single_use_consumed": True,
        "latest_generation_3_observation_confirmed": True,
        "fresh_exact_item_metadata_read_performed": True,
        "fresh_remote_version_current": True,
        "staged_content_integrity_verified": True,
        "malware_scan_completed": True,
        "canonical_document_write_completed": True,
        "document_created": True,
        "evidence_admitted": True,
        "admission_execution_performed": True,
        "remote_list_performed": False,
        "remote_content_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "staged_storage_write_performed": False,
        "staged_storage_delete_performed": False,
        "content_parsed": False,
        "content_extracted": False,
        "processing_enqueued": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_sync_started": False,
    }


def _scope_hash(
    authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization,
    *,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(authorization.organization_id),
            "claim_id": str(authorization.claim_id),
            "profile_id": str(authorization.profile_id),
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "generation_3_change_detection_execution_id": str(
                authorization.generation_3_change_detection_execution_id
            ),
            "checkpoint_generation_3_execution_id": str(
                authorization.checkpoint_generation_3_execution_id
            ),
            "authorized_projection_hash": authorization.authorized_projection_hash,
            "candidate_content_proof_hash": authorization.candidate_content_proof_hash,
            "candidate_completion_hash": authorization.candidate_completion_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceEvidenceAdmissionExecution) -> str:
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


def _completion_hash(execution: ExternalDocumentSourceEvidenceAdmissionExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "status": execution.status,
            "document_id": str(execution.document_id),
            "fresh_projection_hash": execution.fresh_projection_hash,
            "fresh_display_name_hash": execution.fresh_display_name_hash,
            "fresh_version_token_hash": execution.fresh_version_token_hash,
            "fresh_byte_size": execution.fresh_byte_size,
            "fresh_mime_type_class": execution.fresh_mime_type_class,
            "staged_content_sha256": execution.staged_content_sha256,
            "staged_content_byte_count": execution.staged_content_byte_count,
            "staged_storage_object_key_hash": execution.staged_storage_object_key_hash,
            "document_file_hash": execution.document_file_hash,
            "document_file_size_bytes": execution.document_file_size_bytes,
            "document_filename_hash": execution.document_filename_hash,
            "canonical_storage_key_hash": execution.canonical_storage_key_hash,
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceEvidenceAdmissionExecutionReceipt) -> str:
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
    execution: ExternalDocumentSourceEvidenceAdmissionExecution,
) -> list[ExternalDocumentSourceEvidenceAdmissionExecutionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceEvidenceAdmissionExecutionReceipt)
            .where(
                ExternalDocumentSourceEvidenceAdmissionExecutionReceipt.organization_id
                == execution.organization_id,
                ExternalDocumentSourceEvidenceAdmissionExecutionReceipt.execution_id
                == execution.id,
            )
            .order_by(
                ExternalDocumentSourceEvidenceAdmissionExecutionReceipt.sequence_number.asc()
            )
        ).all()
    )


def _get_document(
    db: Session,
    execution: ExternalDocumentSourceEvidenceAdmissionExecution,
) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == execution.document_id,
            Document.organization_id == execution.organization_id,
            Document.claim_id == execution.claim_id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise ExternalDocumentSourceConflictError("Admitted external Evidence Document lineage is missing")
    return document


def _ensure_execution_integrity(
    db: Session,
    execution: ExternalDocumentSourceEvidenceAdmissionExecution,
) -> None:
    authorization = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceEvidenceAdmissionAuthorization.id == execution.authorization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.organization_id == execution.organization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.profile_id == execution.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError("Evidence admission execution authorization lineage is missing")
    _ensure_authorization_integrity(db, authorization)
    document = _get_document(db, execution)

    if (
        execution.claim_id != authorization.claim_id
        or execution.generation_3_change_detection_execution_id
        != authorization.generation_3_change_detection_execution_id
        or execution.checkpoint_generation_3_execution_id
        != authorization.checkpoint_generation_3_execution_id
        or execution.provider_kind != authorization.provider_kind
        or execution.profile_hash != authorization.profile_hash
        or execution.authorization_hash != authorization.authorization_hash
        or execution.authorized_projection_hash != authorization.authorized_projection_hash
        or execution.observation_completion_hash != authorization.observation_completion_hash
        or execution.candidate_content_proof_hash != authorization.candidate_content_proof_hash
        or execution.candidate_completion_hash != authorization.candidate_completion_hash
        or execution.status != "admitted"
        or execution.fresh_projection_hash != authorization.authorized_projection_hash
        or execution.fresh_display_name_hash != authorization.authorized_display_name_hash
        or execution.fresh_version_token_hash != authorization.authorized_version_token_hash
        or (
            authorization.authorized_byte_size is not None
            and execution.fresh_byte_size != authorization.authorized_byte_size
        )
        or execution.fresh_mime_type_class != authorization.authorized_mime_type_class
        or execution.document_file_hash != document.file_hash
        or execution.document_file_size_bytes != document.file_size_bytes
        or execution.document_filename_hash
        != hashlib.sha256(document.original_filename.encode("utf-8")).hexdigest()
        or execution.canonical_storage_key_hash
        != hashlib.sha256(document.storage_key.encode("utf-8")).hexdigest()
        or document.malware_scan_status != DocumentMalwareScanStatus.CLEAN
    ):
        raise ExternalDocumentSourceConflictError("Evidence admission execution lineage/custody drifted")

    expected_scope = _scope_hash(authorization, request_key=execution.request_key)
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Evidence admission execution request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Evidence admission execution completion integrity failed")
    for field, expected in _safety().items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Evidence admission execution safety boundary drifted")

    rows = _receipts(db, execution)
    if len(rows) != 1:
        raise ExternalDocumentSourceConflictError("Evidence admission execution receipt lifecycle drifted")
    receipt = rows[0]
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
        raise ExternalDocumentSourceConflictError("Evidence admission execution receipt integrity drifted")
    for field, expected in _safety().items():
        if bool(getattr(receipt, field)) != expected:
            raise ExternalDocumentSourceConflictError("Evidence admission execution receipt safety boundary drifted")


def _authorization_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceEvidenceAdmissionAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionAuthorization)
        .where(
            ExternalDocumentSourceEvidenceAdmissionAuthorization.id == authorization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.organization_id == organization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.profile_id == profile_id,
        )
        .with_for_update()
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError("Evidence admission authorization not found")
    _ensure_authorization_integrity(db, authorization)
    return authorization


def _fresh_projection(
    db: Session,
    authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization,
):
    observation = get_external_document_source_generation_3_change_detection(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        execution_id=authorization.generation_3_change_detection_execution_id,
    )
    latest = _latest_completed_observation(db, observation=observation)
    if latest is None or latest.id != observation.id:
        raise ExternalDocumentSourceConflictError(
            "Evidence admission authorization is stale because a newer generation-3 observation exists"
        )

    checkpoint = _checkpoint_generation_3(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        execution_id=authorization.checkpoint_generation_3_execution_id,
    )
    candidate, _source_observation, _listing, _item, profile, locator, policy, _baseline, baseline_hash = _lineage(
        db, checkpoint
    )
    if (
        candidate.content_proof_hash != authorization.candidate_content_proof_hash
        or candidate.completion_hash != authorization.candidate_completion_hash
        or baseline_hash != authorization.authorized_projection_hash
    ):
        raise ExternalDocumentSourceConflictError("Authorized generation-3 staged-content lineage drifted")

    adapter = _OBSERVATION_ADAPTERS.get((profile.provider_kind, policy.observation_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Exact-item metadata adapter is unavailable for Evidence admission")
    if (
        getattr(adapter, "provider_kind", None) != profile.provider_kind
        or getattr(adapter, "client_kind", None) != policy.client_kind
        or getattr(adapter, "observation_operation_kind", None) != policy.observation_operation_kind
        or getattr(adapter, "provider_origin", None) != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError("Evidence admission metadata adapter policy drifted")
    try:
        result = adapter.read_item_metadata(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Fresh exact-item metadata revalidation failed") from None
    projection = _validate_result(result)
    if projection is None:
        raise ExternalDocumentSourceConflictError("Authorized external file is no longer present")

    fresh_facts = {
        "provider_item_id_hash": hashlib.sha256(projection.provider_item_id.encode("utf-8")).hexdigest(),
        "item_kind": projection.item_kind,
        "display_name_hash": hashlib.sha256(projection.display_name.encode("utf-8")).hexdigest(),
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
    fresh_hash = _projection_hash(fresh_facts)
    if (
        projection.item_kind != "file"
        or fresh_hash != authorization.authorized_projection_hash
        or fresh_facts["display_name_hash"] != authorization.authorized_display_name_hash
        or fresh_facts["version_token_hash"] != authorization.authorized_version_token_hash
        or fresh_facts["byte_size"] != authorization.authorized_byte_size
        or fresh_facts["mime_type_class"] != authorization.authorized_mime_type_class
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized external file changed after human authorization; a new observation and authorization are required"
        )
    return candidate, projection, fresh_hash, fresh_facts


def _read_staged_payload(candidate):
    if (
        candidate.content_sha256 is None
        or candidate.content_byte_count is None
        or candidate.content_proof_hash is None
        or candidate.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Authorized staged content proof is incomplete")
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
            raise ExternalDocumentSourceConflictError("Authorized staged object metadata drifted")
        payload = store.get_bytes(
            storage_key=candidate.storage_object_key,
            expected_sha256=candidate.content_sha256,
        )
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise ExternalDocumentSourceConflictError("Authorized staged object is missing") from None
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError("Authorized staged object integrity verification failed") from None
    if (
        len(payload) != candidate.content_byte_count
        or hashlib.sha256(payload).hexdigest() != candidate.content_sha256
    ):
        raise ExternalDocumentSourceConflictError("Authorized staged bytes drifted from their content proof")
    return payload


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


def execute_external_document_source_evidence_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    executed_by_id: UUID,
    request_key: str,
    execution_reason: str,
    document_type: str | None,
    confidentiality_level: ConfidentialityLevel,
) -> tuple[ExternalDocumentSourceEvidenceAdmissionExecution, str]:
    request_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    execution_reason = _normalize_text(execution_reason, field="reason", minimum=20, maximum=2000)
    normalized_document_type = (document_type.strip()[:100] or None) if document_type else None

    authorization = _authorization_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    if authorization.authorized_by_id != executed_by_id:
        raise ExternalDocumentSourceConflictError(
            "Evidence admission execution must be performed by the same human actor who recorded the authorization"
        )
    _active_claim(db, organization_id=organization_id, claim_id=authorization.claim_id)

    existing = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionExecution).where(
            ExternalDocumentSourceEvidenceAdmissionExecution.authorization_id == authorization.id,
            ExternalDocumentSourceEvidenceAdmissionExecution.organization_id == organization_id,
        )
    )
    if existing is not None:
        _ensure_execution_integrity(db, existing)
        document = _get_document(db, existing)
        if (
            existing.profile_id != profile_id
            or existing.request_key != request_key
            or existing.execution_reason != execution_reason
            or existing.executed_by_id != executed_by_id
            or document.document_type != normalized_document_type
            or document.confidentiality_level != confidentiality_level
        ):
            raise ExternalDocumentSourceConflictError(
                "Authorization was already consumed by a different Evidence admission request"
            )
        return existing, "replayed"

    collision = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionExecution).where(
            ExternalDocumentSourceEvidenceAdmissionExecution.organization_id == organization_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.profile_id == profile_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.request_key == request_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError("request_key is already bound to another Evidence admission execution")

    candidate, projection, fresh_hash, fresh_facts = _fresh_projection(db, authorization)
    payload = _read_staged_payload(candidate)
    if len(payload) == 0:
        raise ExternalDocumentSourceConflictError("Empty external files cannot be admitted as Evidence")
    if len(payload) > settings.max_upload_bytes:
        raise ExternalDocumentSourceConflictError(
            "Authorized staged file exceeds the configured Evidence upload limit"
        )
    if authorization.authorized_byte_size is not None and len(payload) != authorization.authorized_byte_size:
        raise ExternalDocumentSourceConflictError("Staged bytes no longer match the authorized remote byte count")

    original_filename = normalize_original_filename(projection.display_name)
    try:
        suffix = validate_upload(original_filename, projection.mime_type_class)
    except HTTPException as exc:
        raise ExternalDocumentSourceConflictError("Authorized external file type is not supported for Evidence admission") from exc
    mime_type = (projection.mime_type_class or "application/octet-stream")[:150]

    duplicate = db.scalar(
        select(Document).where(
            Document.organization_id == organization_id,
            Document.claim_id == authorization.claim_id,
            Document.file_hash == candidate.content_sha256,
            Document.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ExternalDocumentSourceConflictError("These bytes already exist in the Claim Evidence record")
    if not settings.malware_scan_enabled:
        raise ExternalDocumentSourceConflictError(
            "Evidence admission is blocked because authoritative malware scanning is disabled"
        )

    local_storage = _storage()
    temporary_id = uuid4()
    quarantine_key = make_quarantine_key(
        organization_id=organization_id,
        claim_id=authorization.claim_id,
        upload_id=temporary_id,
        suffix=suffix,
    )
    document_id = uuid4()
    canonical_key = make_storage_key(
        organization_id=organization_id,
        claim_id=authorization.claim_id,
        document_id=document_id,
        suffix=suffix,
    )
    promoted = False
    temp_exists = False
    committed = False
    try:
        stored = local_storage.save_bytes(payload, quarantine_key)
        temp_exists = True
        if (
            stored.file_hash != candidate.content_sha256
            or stored.file_size_bytes != candidate.content_byte_count
        ):
            raise ExternalDocumentSourceConflictError("Local Evidence quarantine copy failed integrity verification")
        try:
            validate_file_signature(local_storage, quarantine_key, suffix)
        except HTTPException as exc:
            temp_exists = False
            raise ExternalDocumentSourceConflictError(
                "Authorized external bytes do not match the declared file type"
            ) from exc

        attempted_at = _utc_now()
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
                "Malware was detected during external Evidence admission"
            )

        local_storage.promote(quarantine_key, canonical_key)
        temp_exists = False
        promoted = True

        document = Document(
            id=document_id,
            organization_id=organization_id,
            claim_id=authorization.claim_id,
            uploaded_by_id=executed_by_id,
            source_admission_note=execution_reason[:1000],
            document_family_id=document_id,
            filename=original_filename,
            original_filename=original_filename,
            document_type=normalized_document_type,
            mime_type=mime_type,
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            storage_key=canonical_key,
            confidentiality_level=confidentiality_level,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
            malware_scanned_at=attempted_at,
        )
        db.add(document)
        db.flush()

        executed_at = _utc_now()
        execution = ExternalDocumentSourceEvidenceAdmissionExecution(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=authorization.claim_id,
            profile_id=profile_id,
            authorization_id=authorization.id,
            generation_3_change_detection_execution_id=authorization.generation_3_change_detection_execution_id,
            checkpoint_generation_3_execution_id=authorization.checkpoint_generation_3_execution_id,
            successor_versioned_restaging_execution_id=candidate.id,
            document_id=document.id,
            provider_kind=authorization.provider_kind,
            profile_hash=authorization.profile_hash,
            authorization_hash=authorization.authorization_hash,
            authorized_projection_hash=authorization.authorized_projection_hash,
            observation_completion_hash=authorization.observation_completion_hash,
            candidate_content_proof_hash=authorization.candidate_content_proof_hash,
            candidate_completion_hash=authorization.candidate_completion_hash,
            fresh_projection_hash=fresh_hash,
            fresh_display_name_hash=fresh_facts["display_name_hash"],
            fresh_version_token_hash=fresh_facts["version_token_hash"],
            fresh_byte_size=len(payload),
            fresh_mime_type_class=fresh_facts["mime_type_class"],
            staged_content_sha256=candidate.content_sha256,
            staged_content_byte_count=candidate.content_byte_count,
            staged_storage_object_key_hash=candidate.storage_object_key_hash,
            document_file_hash=document.file_hash,
            document_file_size_bytes=document.file_size_bytes,
            document_filename_hash=hashlib.sha256(original_filename.encode("utf-8")).hexdigest(),
            canonical_storage_key_hash=hashlib.sha256(canonical_key.encode("utf-8")).hexdigest(),
            request_key=request_key,
            scope_hash=_scope_hash(authorization, request_key=request_key),
            request_hash="",
            status="admitted",
            executed_by_id=executed_by_id,
            execution_reason=execution_reason,
            executed_at=executed_at,
            completion_hash="",
            **_safety(),
        )
        execution.request_hash = _request_hash(execution)
        execution.completion_hash = _completion_hash(execution)
        db.add(execution)
        db.flush()

        receipt = ExternalDocumentSourceEvidenceAdmissionExecutionReceipt(
            id=uuid4(),
            organization_id=organization_id,
            execution_id=execution.id,
            sequence_number=1,
            event_type="admitted",
            status_after="admitted",
            actor_id=executed_by_id,
            occurred_at=executed_at,
            reason=execution_reason,
            scope_hash=execution.scope_hash,
            decision_hash=execution.completion_hash,
            prior_receipt_hash=None,
            receipt_hash="",
            **_safety(),
        )
        receipt.receipt_hash = _receipt_hash(receipt)
        db.add(receipt)
        db.flush()
        _ensure_execution_integrity(db, execution)

        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=executed_by_id,
            action="ADMIT_EXTERNAL_DOCUMENT_SOURCE_TO_EVIDENCE",
            entity_type="document",
            entity_id=document.id,
            new_values={
                "claim_id": str(authorization.claim_id),
                "document_id": str(document.id),
                "evidence_admission_execution_id": str(execution.id),
                "evidence_admission_authorization_id": str(authorization.id),
                "provider_kind": authorization.provider_kind,
                "document_type": document.document_type,
                "confidentiality_level": document.confidentiality_level.value,
                "file_size_bytes": document.file_size_bytes,
                "file_hash": document.file_hash,
                "malware_scan_status": document.malware_scan_status.value,
                "processing_enqueued": False,
            },
            details=(
                "A human-authorized external file version was revalidated using one exact metadata read, "
                "admitted from its immutable governed staging object after fresh integrity/signature/malware checks, "
                "and written to canonical Document storage. No remote content reread, OCR, parsing, indexing, AI, "
                "Claim mutation, checkpoint advancement or background synchronization was started."
            ),
        )
        db.commit()
        committed = True
        db.refresh(execution)
        return execution, "admitted"
    except SQLAlchemyError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "Evidence admission was committed but response finalization failed; replay the same request key"
            ) from exc
        db.rollback()
        _cleanup_local_storage(
            local_storage=local_storage,
            promoted=promoted,
            temp_exists=temp_exists,
            canonical_key=canonical_key,
            quarantine_key=quarantine_key,
        )
        raise ExternalDocumentSourceConflictError("Evidence admission could not be committed safely") from exc
    except StorageError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "Evidence admission was committed but local response finalization failed; replay the same request key"
            ) from exc
        db.rollback()
        _cleanup_local_storage(
            local_storage=local_storage,
            promoted=promoted,
            temp_exists=temp_exists,
            canonical_key=canonical_key,
            quarantine_key=quarantine_key,
        )
        raise ExternalDocumentSourceConflictError("Local Evidence storage operation failed") from exc
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


def get_external_document_source_evidence_admission_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceEvidenceAdmissionExecution:
    execution = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionExecution).where(
            ExternalDocumentSourceEvidenceAdmissionExecution.id == execution_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.organization_id == organization_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.profile_id == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError("Evidence admission execution not found")
    _ensure_execution_integrity(db, execution)
    return execution


def list_external_document_source_evidence_admission_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> list[ExternalDocumentSourceEvidenceAdmissionExecutionReceipt]:
    execution = get_external_document_source_evidence_admission_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
