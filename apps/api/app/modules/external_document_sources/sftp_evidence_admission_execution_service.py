from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
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
from app.modules.external_document_sources import sftp_change_detection_service as base_change
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataRequest,
    _effective_remote_path,
    _validate_adapter_result,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_service import (
    _active_claim,
    _eligible_observation,
    _ensure_integrity as _ensure_authorization_integrity,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
    ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    _active_binding_and_profile,
    _load_listing_and_entry,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    _configured_store,
)


_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


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
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
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
        "upstream_authorization_verified": True,
        "authorization_single_use_consumed": True,
        "latest_generation3_observation_confirmed": True,
        "fresh_exact_file_metadata_read_performed": True,
        "fresh_remote_version_current": True,
        "staged_storage_read_performed": True,
        "staged_content_integrity_verified": True,
        "malware_scan_completed": True,
        "canonical_document_write_completed": True,
        "document_created": True,
        "evidence_admitted": True,
        "admission_execution_performed": True,
        "secret_resolution_performed": True,
        "provider_network_performed": True,
        "ssh_transport_performed": True,
        "host_key_verification_performed": True,
        "host_key_verified": True,
        "authentication_performed": True,
        "authentication_succeeded": True,
        "sftp_session_opened": True,
        "sftp_session_closed": True,
        "remote_stat_performed": True,
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


def _scope_hash(
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
    *,
    request_key: str,
) -> str:
    return _canonical_hash({
        "organization_id": str(authorization.organization_id),
        "claim_id": str(authorization.claim_id),
        "profile_id": str(authorization.profile_id),
        "authorization_id": str(authorization.id),
        "authorization_hash": authorization.authorization_hash,
        "generation3_change_detection_id": str(
            authorization.generation3_change_detection_id
        ),
        "generation3_checkpoint_advancement_id": str(
            authorization.generation3_checkpoint_advancement_id
        ),
        "generation3_restaging_id": str(authorization.generation3_restaging_id),
        "authorized_projection_hash": authorization.authorized_projection_hash,
        "authorized_content_sha256": authorization.authorized_content_sha256,
        "authorized_storage_object_key_hash": (
            authorization.authorized_storage_object_key_hash
        ),
        "candidate_content_proof_hash": authorization.candidate_content_proof_hash,
        "candidate_completion_hash": authorization.candidate_completion_hash,
        "request_key": request_key,
    })


def _request_hash(
    execution: ExternalDocumentSourceSftpEvidenceAdmissionExecution,
) -> str:
    return _canonical_hash({
        "execution_id": str(execution.id),
        "scope_hash": execution.scope_hash,
        "executed_by_id": str(execution.executed_by_id),
        "execution_reason": execution.execution_reason,
        "executed_at": _iso(execution.executed_at),
        **_safety(),
    })


def _completion_hash(
    execution: ExternalDocumentSourceSftpEvidenceAdmissionExecution,
) -> str:
    return _canonical_hash({
        "execution_id": str(execution.id),
        "scope_hash": execution.scope_hash,
        "request_hash": execution.request_hash,
        "status": execution.status,
        "document_id": str(execution.document_id),
        "fresh_projection_hash": execution.fresh_projection_hash,
        "fresh_byte_size": execution.fresh_byte_size,
        "fresh_modified_at": _iso(execution.fresh_modified_at),
        "fresh_metadata_id_hash": execution.fresh_metadata_id_hash,
        "authentication_method": execution.authentication_method,
        "latency_class": execution.latency_class,
        "staged_content_sha256": execution.staged_content_sha256,
        "staged_content_byte_count": execution.staged_content_byte_count,
        "staged_storage_object_key_hash": execution.staged_storage_object_key_hash,
        "document_file_hash": execution.document_file_hash,
        "document_file_size_bytes": execution.document_file_size_bytes,
        "document_filename_hash": execution.document_filename_hash,
        "canonical_storage_key_hash": execution.canonical_storage_key_hash,
        **_safety(),
    })


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt,
) -> str:
    return _canonical_hash({
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
    })


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceSftpEvidenceAdmissionExecution,
):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt)
            .where(
                ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt.organization_id
                == execution.organization_id,
                ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt.execution_id
                == execution.id,
            )
            .order_by(
                ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt.sequence_number.asc()
            )
        ).all()
    )


def _get_document(
    db: Session,
    execution: ExternalDocumentSourceSftpEvidenceAdmissionExecution,
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
        raise ExternalDocumentSourceConflictError(
            "Admitted SFTP Evidence Document lineage is missing"
        )
    return document


def _ensure_execution_integrity(
    db: Session,
    execution: ExternalDocumentSourceSftpEvidenceAdmissionExecution,
) -> None:
    authorization = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.id
            == execution.authorization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == execution.organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == execution.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission execution authorization lineage is missing"
        )
    _ensure_authorization_integrity(db, authorization)
    document = _get_document(db, execution)

    if (
        execution.claim_id != authorization.claim_id
        or execution.generation3_change_detection_id
        != authorization.generation3_change_detection_id
        or execution.generation3_checkpoint_advancement_id
        != authorization.generation3_checkpoint_advancement_id
        or execution.generation3_restaging_id
        != authorization.generation3_restaging_id
        or execution.provider_kind != "sftp"
        or execution.profile_hash != authorization.profile_hash
        or execution.authorization_hash != authorization.authorization_hash
        or execution.authorized_projection_hash
        != authorization.authorized_projection_hash
        or execution.observation_completion_hash
        != authorization.observation_completion_hash
        or execution.candidate_content_proof_hash
        != authorization.candidate_content_proof_hash
        or execution.candidate_completion_hash
        != authorization.candidate_completion_hash
        or execution.status != "admitted"
        or execution.fresh_projection_hash
        != authorization.authorized_projection_hash
        or execution.fresh_byte_size != authorization.authorized_byte_size
        or (
            (execution.fresh_modified_at is None)
            != (authorization.authorized_modified_at is None)
        )
        or (
            execution.fresh_modified_at is not None
            and _aware(execution.fresh_modified_at)
            != _aware(authorization.authorized_modified_at)
        )
        or execution.fresh_metadata_id_hash
        != authorization.authorized_metadata_id_hash
        or execution.staged_content_sha256
        != authorization.authorized_content_sha256
        or execution.staged_content_byte_count
        != authorization.authorized_byte_size
        or execution.staged_storage_object_key_hash
        != authorization.authorized_storage_object_key_hash
        or execution.document_file_hash != document.file_hash
        or execution.document_file_size_bytes != document.file_size_bytes
        or execution.document_filename_hash
        != hashlib.sha256(document.original_filename.encode("utf-8")).hexdigest()
        or execution.canonical_storage_key_hash
        != hashlib.sha256(document.storage_key.encode("utf-8")).hexdigest()
        or document.malware_scan_status != DocumentMalwareScanStatus.CLEAN
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission execution lineage/custody drifted"
        )

    expected_scope = _scope_hash(
        authorization,
        request_key=execution.request_key,
    )
    if (
        execution.scope_hash != expected_scope
        or execution.request_hash != _request_hash(execution)
        or execution.completion_hash != _completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission execution integrity failed"
        )
    for field, expected in _safety().items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence admission execution safety boundary drifted"
            )

    rows = _receipts(db, execution)
    if len(rows) != 1:
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission execution receipt lifecycle drifted"
        )
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
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission execution receipt integrity drifted"
        )
    for field, expected in _safety().items():
        if bool(getattr(receipt, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence admission execution receipt safety boundary drifted"
            )


def _authorization_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
):
    authorization = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization)
        .where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.id
            == authorization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP Evidence admission authorization not found"
        )
    _ensure_authorization_integrity(db, authorization)
    return authorization


def _fresh_currentness(
    db: Session,
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
):
    observation, checkpoint, candidate = _eligible_observation(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        execution_id=authorization.generation3_change_detection_id,
        require_latest=True,
        lock_checkpoint=True,
    )
    if (
        checkpoint.id != authorization.generation3_checkpoint_advancement_id
        or candidate.id != authorization.generation3_restaging_id
        or checkpoint.successor_checkpoint_state_hash
        != authorization.checkpoint_state_hash
        or checkpoint.completion_hash != authorization.checkpoint_completion_hash
        or candidate.content_proof_hash
        != authorization.candidate_content_proof_hash
        or candidate.completion_hash != authorization.candidate_completion_hash
        or candidate.content_sha256 != authorization.authorized_content_sha256
        or candidate.content_byte_count != authorization.authorized_byte_size
        or candidate.storage_object_key_hash
        != authorization.authorized_storage_object_key_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence authorization generation-3 custody drifted"
        )

    listing, entry = _load_listing_and_entry(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        listing_id=candidate.directory_listing_id,
        entry_id=candidate.listing_entry_id,
        for_update=False,
    )
    binding, normalized = _active_binding_and_profile(db, listing)
    if (
        binding.id != candidate.credential_reference_binding_id
        or entry.entry_kind != "file"
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence exact-file locator lineage drifted"
        )

    adapter = base_change._METADATA_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter is unavailable for Evidence admission"
        )
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if (
        not isinstance(adapter_kind, str)
        or not base_change._SAFE_ADAPTER_KIND.fullmatch(adapter_kind)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter kind is invalid"
        )

    request = SftpExactFileMetadataRequest(
        hostname=listing.destination_hostname,
        port=listing.destination_port,
        username=normalized["username"],
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
        remote_root_path=normalized["remote_root_path"],
        entry_relative_path=entry.relative_path,
        effective_remote_path=_effective_remote_path(
            normalized["remote_root_path"],
            entry.relative_path,
        ),
    )
    try:
        raw_result = adapter.stat_metadata(request)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "Fresh SFTP exact-file metadata revalidation failed"
        ) from None
    fresh = _validate_adapter_result(
        raw_result,
        expected_auth_kind=binding.authentication_kind,
    )
    if (
        fresh["result_status"] == "missing"
        or fresh["observed_projection_hash"] is None
        or fresh["observed_entry_kind"] != "file"
        or fresh["observed_byte_size"] is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP file is no longer present"
        )
    if (
        fresh["observed_projection_hash"]
        != authorization.authorized_projection_hash
        or fresh["observed_byte_size"] != authorization.authorized_byte_size
        or fresh["observed_metadata_id_hash"]
        != authorization.authorized_metadata_id_hash
        or (
            (fresh["observed_modified_at"] is None)
            != (authorization.authorized_modified_at is None)
        )
        or (
            fresh["observed_modified_at"] is not None
            and _aware(fresh["observed_modified_at"])
            != _aware(authorization.authorized_modified_at)
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP file changed after human authorization; a new observation and authorization are required"
        )

    basename = PurePosixPath(entry.relative_path).name
    if not basename:
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP file has no admissible filename"
        )
    return candidate, basename, fresh


def _read_staged_payload(
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
    candidate,
):
    if (
        candidate.content_sha256 is None
        or candidate.content_byte_count is None
        or candidate.content_proof_hash is None
        or candidate.completion_hash is None
        or candidate.stored_etag is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP staged content proof is incomplete"
        )
    if (
        candidate.content_sha256 != authorization.authorized_content_sha256
        or candidate.content_byte_count != authorization.authorized_byte_size
        or candidate.storage_object_key_hash
        != authorization.authorized_storage_object_key_hash
        or hashlib.sha256(candidate.storage_object_key.encode("utf-8")).hexdigest()
        != authorization.authorized_storage_object_key_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP staged object binding drifted"
        )

    store = _configured_store()
    try:
        metadata = store.head_object(storage_key=candidate.storage_object_key)
        if (
            metadata.file_hash.lower() != candidate.content_sha256.lower()
            or metadata.file_size_bytes != candidate.content_byte_count
            or (
                metadata.etag is not None
                and metadata.etag != candidate.stored_etag
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "Authorized SFTP staged object metadata drifted"
            )
        payload = store.get_bytes(
            storage_key=candidate.storage_object_key,
            expected_sha256=candidate.content_sha256,
        )
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP staged object is missing"
        ) from None
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP staged object integrity verification failed"
        ) from None

    if (
        len(payload) != candidate.content_byte_count
        or hashlib.sha256(payload).hexdigest() != candidate.content_sha256
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP staged bytes drifted from their content proof"
        )
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


def execute_external_document_source_sftp_evidence_admission(
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
):
    request_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    execution_reason = _normalize_text(
        execution_reason,
        field="reason",
        minimum=20,
        maximum=2000,
    )
    normalized_document_type = (
        (document_type.strip()[:100] or None)
        if document_type
        else None
    )

    authorization = _authorization_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    if authorization.authorized_by_id != executed_by_id:
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission must be performed by the same human actor who recorded the authorization"
        )
    _active_claim(
        db,
        organization_id=organization_id,
        claim_id=authorization.claim_id,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionExecution).where(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.authorization_id
            == authorization.id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.organization_id
            == organization_id,
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
                "SFTP authorization was already consumed by a different Evidence admission request"
            )
        return existing, "replayed"

    collision = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionExecution).where(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.profile_id
            == profile_id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.request_key
            == request_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "request_key is already bound to another SFTP Evidence admission execution"
        )

    candidate, raw_basename, fresh = _fresh_currentness(db, authorization)
    payload = _read_staged_payload(authorization, candidate)

    if len(payload) == 0:
        raise ExternalDocumentSourceConflictError(
            "Empty SFTP files cannot be admitted as Evidence"
        )
    if len(payload) > settings.max_upload_bytes:
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP staged file exceeds the configured Evidence upload limit"
        )
    if len(payload) != authorization.authorized_byte_size:
        raise ExternalDocumentSourceConflictError(
            "SFTP staged bytes no longer match the authorized remote byte count"
        )

    original_filename = normalize_original_filename(raw_basename)
    suffix_guess = PurePosixPath(original_filename).suffix.lower()
    mime_type = _MIME_BY_SUFFIX.get(suffix_guess)
    try:
        suffix = validate_upload(original_filename, mime_type)
    except HTTPException as exc:
        raise ExternalDocumentSourceConflictError(
            "Authorized SFTP file type is not supported for Evidence admission"
        ) from exc
    mime_type = _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")

    duplicate = db.scalar(
        select(Document).where(
            Document.organization_id == organization_id,
            Document.claim_id == authorization.claim_id,
            Document.file_hash == candidate.content_sha256,
            Document.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ExternalDocumentSourceConflictError(
            "These bytes already exist in the Claim Evidence record"
        )
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
            raise ExternalDocumentSourceConflictError(
                "Local SFTP Evidence quarantine copy failed integrity verification"
            )
        try:
            validate_file_signature(local_storage, quarantine_key, suffix)
        except HTTPException as exc:
            temp_exists = False
            raise ExternalDocumentSourceConflictError(
                "Authorized SFTP bytes do not match the declared file type"
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
                "Malware was detected during SFTP Evidence admission"
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
        execution = ExternalDocumentSourceSftpEvidenceAdmissionExecution(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=authorization.claim_id,
            profile_id=profile_id,
            authorization_id=authorization.id,
            generation3_change_detection_id=authorization.generation3_change_detection_id,
            generation3_checkpoint_advancement_id=authorization.generation3_checkpoint_advancement_id,
            generation3_restaging_id=authorization.generation3_restaging_id,
            document_id=document.id,
            provider_kind="sftp",
            profile_hash=authorization.profile_hash,
            authorization_hash=authorization.authorization_hash,
            authorized_projection_hash=authorization.authorized_projection_hash,
            observation_completion_hash=authorization.observation_completion_hash,
            candidate_content_proof_hash=authorization.candidate_content_proof_hash,
            candidate_completion_hash=authorization.candidate_completion_hash,
            fresh_projection_hash=fresh["observed_projection_hash"],
            fresh_byte_size=fresh["observed_byte_size"],
            fresh_modified_at=fresh["observed_modified_at"],
            fresh_metadata_id_hash=fresh["observed_metadata_id_hash"],
            authentication_method=fresh["authentication_method"],
            latency_class=fresh["latency_class"],
            staged_content_sha256=candidate.content_sha256,
            staged_content_byte_count=candidate.content_byte_count,
            staged_storage_object_key_hash=candidate.storage_object_key_hash,
            document_file_hash=document.file_hash,
            document_file_size_bytes=document.file_size_bytes,
            document_filename_hash=hashlib.sha256(
                original_filename.encode("utf-8")
            ).hexdigest(),
            canonical_storage_key_hash=hashlib.sha256(
                canonical_key.encode("utf-8")
            ).hexdigest(),
            request_key=request_key,
            scope_hash=_scope_hash(
                authorization,
                request_key=request_key,
            ),
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

        receipt = ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt(
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
            action="ADMIT_SFTP_EXTERNAL_DOCUMENT_SOURCE_TO_EVIDENCE",
            entity_type="document",
            entity_id=document.id,
            new_values={
                "claim_id": str(authorization.claim_id),
                "document_id": str(document.id),
                "sftp_evidence_admission_execution_id": str(execution.id),
                "sftp_evidence_admission_authorization_id": str(authorization.id),
                "provider_kind": "sftp",
                "document_type": document.document_type,
                "confidentiality_level": document.confidentiality_level.value,
                "file_size_bytes": document.file_size_bytes,
                "file_hash": document.file_hash,
                "malware_scan_status": document.malware_scan_status.value,
                "processing_enqueued": False,
            },
            details=(
                "A human-authorized exact-current SFTP file was revalidated using one "
                "bounded exact-file metadata stat, admitted only from its immutable governed "
                "generation-3 staging object after fresh integrity/signature/malware checks, "
                "and written to canonical Document storage. No remote content reread, OCR, "
                "parsing, indexing, AI, Claim mutation, checkpoint advancement or background "
                "synchronization was started."
            ),
        )
        db.commit()
        committed = True
        db.refresh(execution)
        return execution, "admitted"
    except SQLAlchemyError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence admission was committed but response finalization failed; replay the same request key"
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
            "SFTP Evidence admission could not be committed safely"
        ) from exc
    except StorageError as exc:
        if committed:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence admission was committed but local response finalization failed; replay the same request key"
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
            "Local SFTP Evidence storage operation failed"
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


def get_external_document_source_sftp_evidence_admission_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionExecution).where(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.id == execution_id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.profile_id
            == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP Evidence admission execution not found"
        )
    _ensure_execution_integrity(db, execution)
    return execution


def list_external_document_source_sftp_evidence_admission_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_sftp_evidence_admission_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
