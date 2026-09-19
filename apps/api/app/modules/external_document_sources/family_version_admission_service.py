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
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.evidence_admission_authorization_service import (
    _ensure_integrity as _ensure_authorization_integrity,
)
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.evidence_admission_execution_service import (
    _authorization_for_update,
    _cleanup_local_storage,
    _fresh_projection,
    _read_staged_payload,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
)
from app.modules.external_document_sources.family_version_admission_models import (
    ExternalDocumentSourceFamilyVersionAdmissionExecution,
    ExternalDocumentSourceFamilyVersionAdmissionReceipt,
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
        "upstream_authorization_verified": True,
        "durable_family_binding_verified": True,
        "stable_source_identity_verified": True,
        "authorization_single_use_consumed": True,
        "latest_generation_3_observation_confirmed": True,
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


def _scope_hash(
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    authorization: ExternalDocumentSourceEvidenceAdmissionAuthorization,
    *,
    prior_document: Document,
    prior_projection_hash: str,
    prior_provider_version_hash: str | None,
    new_version_number: int,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(binding.organization_id),
            "claim_id": str(binding.claim_id),
            "profile_id": str(binding.profile_id),
            "binding_id": str(binding.id),
            "binding_completion_hash": binding.completion_hash,
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "stable_source_item_hash": binding.stable_source_item_hash,
            "document_family_id": str(binding.document_family_id),
            "prior_document_id": str(prior_document.id),
            "prior_version_number": prior_document.version_number,
            "prior_document_file_hash": prior_document.file_hash,
            "prior_projection_hash": prior_projection_hash,
            "prior_provider_version_hash": prior_provider_version_hash,
            "new_version_number": new_version_number,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceFamilyVersionAdmissionExecution) -> str:
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


def _completion_hash(execution: ExternalDocumentSourceFamilyVersionAdmissionExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "status": execution.status,
            "binding_id": str(execution.binding_id),
            "authorization_id": str(execution.authorization_id),
            "document_family_id": str(execution.document_family_id),
            "prior_document_id": str(execution.prior_document_id),
            "prior_version_number": execution.prior_version_number,
            "new_document_id": str(execution.new_document_id),
            "new_version_number": execution.new_version_number,
            "stable_source_item_hash": execution.stable_source_item_hash,
            "fresh_projection_hash": execution.fresh_projection_hash,
            "fresh_version_token_hash": execution.fresh_version_token_hash,
            "staged_content_sha256": execution.staged_content_sha256,
            "staged_content_byte_count": execution.staged_content_byte_count,
            "new_document_file_hash": execution.new_document_file_hash,
            "new_document_file_size_bytes": execution.new_document_file_size_bytes,
            "new_document_filename_hash": execution.new_document_filename_hash,
            "canonical_storage_key_hash": execution.canonical_storage_key_hash,
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceFamilyVersionAdmissionReceipt) -> str:
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


def _documents(
    db: Session,
    execution: ExternalDocumentSourceFamilyVersionAdmissionExecution,
) -> tuple[Document, Document]:
    prior = db.get(Document, execution.prior_document_id)
    new = db.get(Document, execution.new_document_id)
    if prior is None or new is None:
        raise ExternalDocumentSourceConflictError(
            "External Evidence family version admission Document lineage is missing"
        )
    return prior, new


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
            "Current external Evidence family version lacks governed admission lineage"
        )
    _ensure_execution_integrity(db, prior_execution)
    if prior_execution.new_version_number != current_document.version_number:
        raise ExternalDocumentSourceConflictError(
            "Current external Evidence family version lineage drifted"
        )
    return (
        prior_execution.fresh_projection_hash,
        prior_execution.fresh_version_token_hash,
    )


def _ensure_execution_integrity(
    db: Session,
    execution: ExternalDocumentSourceFamilyVersionAdmissionExecution,
) -> None:
    authorization = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceEvidenceAdmissionAuthorization.id
            == execution.authorization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.organization_id
            == execution.organization_id,
            ExternalDocumentSourceEvidenceAdmissionAuthorization.profile_id
            == execution.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "Family-version admission authorization lineage is missing"
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
            "Family-version admission binding lineage is missing"
        )
    _ensure_binding_integrity(db, binding)

    prior, new = _documents(db, execution)
    expected = {
        "claim_id": binding.claim_id,
        "profile_id": binding.profile_id,
        "generation_3_change_detection_execution_id":
            authorization.generation_3_change_detection_execution_id,
        "checkpoint_generation_3_execution_id":
            authorization.checkpoint_generation_3_execution_id,
        "successor_versioned_restaging_execution_id":
            authorization.successor_versioned_restaging_execution_id,
        "document_family_id": binding.document_family_id,
        "provider_kind": binding.provider_kind,
        "profile_hash": binding.profile_hash,
        "stable_source_item_hash": binding.stable_source_item_hash,
        "authorization_hash": authorization.authorization_hash,
        "authorized_projection_hash": authorization.authorized_projection_hash,
        "observation_completion_hash": authorization.observation_completion_hash,
        "candidate_content_proof_hash": authorization.candidate_content_proof_hash,
        "candidate_completion_hash": authorization.candidate_completion_hash,
        "prior_document_file_hash": prior.file_hash,
        "new_document_file_hash": new.file_hash,
        "new_document_file_size_bytes": new.file_size_bytes,
        "status": "admitted",
    }
    for field, value in expected.items():
        if getattr(execution, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Family-version admission integrity drifted at {field}"
            )

    if (
        prior.organization_id != execution.organization_id
        or prior.claim_id != execution.claim_id
        or prior.document_family_id != binding.document_family_id
        or prior.version_number != execution.prior_version_number
        or prior.is_current
        or prior.superseded_by_id != execution.executed_by_id
        or prior.superseded_at is None
        or _aware(prior.superseded_at) != _aware(execution.executed_at)
        or new.organization_id != execution.organization_id
        or new.claim_id != execution.claim_id
        or new.document_family_id != binding.document_family_id
        or new.version_number != execution.new_version_number
        or new.version_number != prior.version_number + 1
        or new.supersedes_document_id != prior.id
        or new.uploaded_by_id != execution.executed_by_id
        or new.replacement_reason != execution.execution_reason
        or new.source_admission_note != execution.execution_reason[:1000]
        or new.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or execution.new_document_filename_hash
        != hashlib.sha256(new.original_filename.encode("utf-8")).hexdigest()
        or execution.canonical_storage_key_hash
        != hashlib.sha256(new.storage_key.encode("utf-8")).hexdigest()
    ):
        raise ExternalDocumentSourceConflictError(
            "Family-version admission canonical Document lineage drifted"
        )

    if (
        execution.new_version_number != execution.prior_version_number + 1
        or execution.fresh_projection_hash != execution.authorized_projection_hash
        or execution.fresh_byte_size != execution.staged_content_byte_count
        or execution.staged_content_sha256 != execution.new_document_file_hash
        or execution.staged_content_byte_count != execution.new_document_file_size_bytes
        or execution.fresh_projection_hash == execution.prior_projection_hash
        or (
            execution.prior_provider_version_hash is not None
            and execution.fresh_version_token_hash is not None
            and execution.prior_provider_version_hash
            == execution.fresh_version_token_hash
        )
    ):
        raise ExternalDocumentSourceConflictError(
            "Family-version admission source-version lineage drifted"
        )

    expected_scope = _scope_hash(
        binding,
        authorization,
        prior_document=prior,
        prior_projection_hash=execution.prior_projection_hash,
        prior_provider_version_hash=execution.prior_provider_version_hash,
        new_version_number=execution.new_version_number,
        request_key=execution.request_key,
    )
    if (
        execution.scope_hash != expected_scope
        or execution.request_hash != _request_hash(execution)
        or execution.completion_hash != _completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError(
            "Family-version admission cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(execution, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Family-version admission safety boundary drifted"
            )

    receipts = _receipts(db, execution)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Family-version admission receipt lifecycle drifted"
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
            "Family-version admission receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Family-version admission receipt safety boundary drifted"
            )


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
    if authorization.authorized_by_id != executed_by_id:
        raise ExternalDocumentSourceConflictError(
            "Later-version admission must be executed by the same human actor who authorized it"
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
            existing.profile_id != profile_id
            or existing.binding_id != binding_id
            or existing.request_key != normalized_key
            or existing.execution_reason != normalized_reason
            or existing.executed_by_id != executed_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Authorization was already consumed by a different family-version admission request"
            )
        return existing, "replayed"

    initial_execution = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionExecution.id).where(
            ExternalDocumentSourceEvidenceAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.authorization_id
            == authorization.id,
        )
    )
    if initial_execution is not None:
        raise ExternalDocumentSourceConflictError(
            "Authorization was already consumed by initial Evidence admission"
        )

    collision = db.scalar(
        select(ExternalDocumentSourceFamilyVersionAdmissionExecution).where(
            ExternalDocumentSourceFamilyVersionAdmissionExecution.organization_id
            == organization_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.profile_id == profile_id,
            ExternalDocumentSourceFamilyVersionAdmissionExecution.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "request_key is already bound to another family-version admission"
        )

    binding = _binding_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    if (
        authorization.claim_id != binding.claim_id
        or authorization.profile_id != binding.profile_id
        or authorization.provider_kind != binding.provider_kind
        or authorization.profile_hash != binding.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization does not belong to the bound Evidence family"
        )

    current_document = db.scalar(
        select(Document)
        .where(
            Document.organization_id == organization_id,
            Document.claim_id == binding.claim_id,
            Document.document_family_id == binding.document_family_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if current_document is None:
        raise ExternalDocumentSourceConflictError(
            "Bound Evidence family has no canonical current Document"
        )

    prior_projection_hash, prior_provider_version_hash = _prior_source_state(
        db,
        binding=binding,
        current_document=current_document,
    )
    if _aware(authorization.authorized_at) < _aware(current_document.created_at):
        raise ExternalDocumentSourceConflictError(
            "Later-version authorization predates the current Evidence version and is stale"
        )

    candidate, projection, fresh_hash, fresh_facts = _fresh_projection(
        db,
        authorization,
    )
    if fresh_facts["provider_item_id_hash"] != binding.stable_source_item_hash:
        raise ExternalDocumentSourceConflictError(
            "Authorized remote item does not match the durable Evidence-family source identity"
        )
    if fresh_hash == prior_projection_hash:
        raise ExternalDocumentSourceConflictError(
            "Authorized remote item is not a later source version"
        )
    if (
        prior_provider_version_hash is not None
        and fresh_facts["version_token_hash"] is not None
        and prior_provider_version_hash == fresh_facts["version_token_hash"]
    ):
        raise ExternalDocumentSourceConflictError(
            "Authorized provider version is already the current Evidence version"
        )

    payload = _read_staged_payload(candidate)
    if len(payload) == 0:
        raise ExternalDocumentSourceConflictError(
            "Empty external files cannot be admitted as a later Evidence version"
        )
    if len(payload) > settings.max_upload_bytes:
        raise ExternalDocumentSourceConflictError(
            "Authorized staged file exceeds the configured Evidence upload limit"
        )
    if (
        authorization.authorized_byte_size is not None
        and len(payload) != authorization.authorized_byte_size
    ):
        raise ExternalDocumentSourceConflictError(
            "Staged bytes no longer match the authorized remote byte count"
        )
    if candidate.content_sha256 == current_document.file_hash:
        raise ExternalDocumentSourceConflictError(
            "Later-version admission cannot duplicate the current Evidence bytes"
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
    temporary_id = uuid4()
    quarantine_key = make_quarantine_key(
        organization_id=organization_id,
        claim_id=binding.claim_id,
        upload_id=temporary_id,
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
            stored.file_hash != candidate.content_sha256
            or stored.file_size_bytes != candidate.content_byte_count
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
        new_version_number = current_document.version_number + 1

        current_document.is_current = False
        current_document.superseded_at = executed_at
        current_document.superseded_by_id = executed_by_id
        db.flush()

        new_document = Document(
            id=new_document_id,
            organization_id=organization_id,
            claim_id=binding.claim_id,
            uploaded_by_id=executed_by_id,
            supersedes_document_id=current_document.id,
            document_family_id=binding.document_family_id,
            version_number=new_version_number,
            is_current=True,
            replacement_reason=normalized_reason,
            source_admission_note=normalized_reason[:1000],
            filename=original_filename,
            original_filename=original_filename,
            document_type=current_document.document_type,
            mime_type=mime_type,
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            storage_key=canonical_key,
            confidentiality_level=current_document.confidentiality_level,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
            malware_scanned_at=scanned_at,
        )
        db.add(new_document)
        db.flush()

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
                "Evidence family current-version invariant was not established"
            )

        execution = ExternalDocumentSourceFamilyVersionAdmissionExecution(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=binding.claim_id,
            profile_id=profile_id,
            binding_id=binding.id,
            authorization_id=authorization.id,
            generation_3_change_detection_execution_id=
                authorization.generation_3_change_detection_execution_id,
            checkpoint_generation_3_execution_id=
                authorization.checkpoint_generation_3_execution_id,
            successor_versioned_restaging_execution_id=
                authorization.successor_versioned_restaging_execution_id,
            document_family_id=binding.document_family_id,
            prior_document_id=current_document.id,
            prior_version_number=current_document.version_number,
            new_document_id=new_document.id,
            new_version_number=new_document.version_number,
            provider_kind=binding.provider_kind,
            profile_hash=binding.profile_hash,
            stable_source_item_hash=binding.stable_source_item_hash,
            authorization_hash=authorization.authorization_hash,
            authorized_projection_hash=authorization.authorized_projection_hash,
            observation_completion_hash=authorization.observation_completion_hash,
            candidate_content_proof_hash=authorization.candidate_content_proof_hash,
            candidate_completion_hash=authorization.candidate_completion_hash,
            prior_projection_hash=prior_projection_hash,
            prior_provider_version_hash=prior_provider_version_hash,
            prior_document_file_hash=current_document.file_hash,
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
            scope_hash=_scope_hash(
                binding,
                authorization,
                prior_document=current_document,
                prior_projection_hash=prior_projection_hash,
                prior_provider_version_hash=prior_provider_version_hash,
                new_version_number=new_version_number,
                request_key=normalized_key,
            ),
            request_hash="",
            status="admitted",
            executed_by_id=executed_by_id,
            execution_reason=normalized_reason,
            executed_at=executed_at,
            completion_hash="",
            **_safety(),
        )
        execution.request_hash = _request_hash(execution)
        execution.completion_hash = _completion_hash(execution)
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
            action="ADMIT_LATER_EXTERNAL_EVIDENCE_VERSION",
            entity_type="document",
            entity_id=new_document.id,
            new_values={
                "claim_id": str(binding.claim_id),
                "evidence_family_binding_id": str(binding.id),
                "family_version_admission_execution_id": str(execution.id),
                "evidence_admission_authorization_id": str(authorization.id),
                "document_family_id": str(binding.document_family_id),
                "prior_document_id": str(current_document.id),
                "prior_version_number": current_document.version_number,
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
                "A separately human-authorized later external source version was "
                "revalidated against exact current remote metadata, copied from its "
                "governed staged object after integrity/signature/malware checks, and "
                "admitted as the next immutable canonical Document version. The prior "
                "Document remains preserved as historical Evidence. No processing, AI, "
                "Claim mutation, checkpoint advancement or background synchronization "
                "was started."
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
    return _receipts(db, execution)
