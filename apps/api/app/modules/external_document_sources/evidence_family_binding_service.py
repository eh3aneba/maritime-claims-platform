from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.evidence_admission_authorization_service import (
    _active_claim,
)
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.evidence_admission_execution_service import (
    _ensure_execution_integrity,
    _get_document,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
    ExternalDocumentSourceEvidenceFamilyBindingReceipt,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_service import (
    _ensure_integrity as _ensure_sftp_authorization_integrity,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_service import (
    _ensure_execution_integrity as _ensure_sftp_execution_integrity,
    _get_document as _get_sftp_document,
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
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _safety() -> dict[str, bool]:
    return {
        "upstream_admission_verified": True,
        "stable_source_identity_derived": True,
        "document_family_verified": True,
        "version_baseline_recorded": True,
        "provider_client_constructed": False,
        "remote_metadata_read_performed": False,
        "remote_content_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "document_created": False,
        "document_mutated": False,
        "processing_enqueued": False,
        "content_extracted": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
        "background_sync_started": False,
    }


@dataclass(frozen=True)
class _ResolvedAdmissionLineage:
    legacy_execution_id: UUID | None
    sftp_execution_id: UUID | None
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    document: Document
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    source_projection_hash: str
    source_observation_completion_hash: str
    admission_completion_hash: str
    admitted_content_sha256: str
    admitted_byte_count: int
    admitted_mime_type_class: str | None
    admitted_provider_version_hash: str | None


def _stable_sftp_source_item_hash(
    *,
    profile_id: UUID,
    relative_path_hash: str,
) -> str:
    return _canonical_hash(
        {
            "provider_kind": "sftp",
            "profile_id": str(profile_id),
            "relative_path_hash": relative_path_hash,
        }
    )


def _verify_sftp_document_baseline(
    db: Session,
    execution: ExternalDocumentSourceSftpEvidenceAdmissionExecution,
    *,
    require_uploaded: bool,
    require_current: bool,
) -> Document:
    document = _get_sftp_document(db, execution)
    if (
        document.id != execution.document_id
        or document.document_family_id != document.id
        or document.version_number != 1
        or document.supersedes_document_id is not None
        or document.file_hash != execution.document_file_hash
        or document.file_size_bytes != execution.document_file_size_bytes
    ):
        raise ExternalDocumentSourceConflictError(
            "Admitted SFTP Document is not a valid initial Evidence-family baseline"
        )
    if require_current and not document.is_current:
        raise ExternalDocumentSourceConflictError(
            "Initial SFTP Evidence-family baseline must still be current when binding is created"
        )
    if require_uploaded and document.processing_status != DocumentProcessingStatus.UPLOADED:
        raise ExternalDocumentSourceConflictError(
            "Admitted SFTP Document baseline was already processed before family binding"
        )
    return document


def _resolve_legacy_admission_lineage(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    require_uploaded: bool,
    require_current: bool,
    for_update: bool,
    missing_is_conflict: bool,
) -> _ResolvedAdmissionLineage:
    stmt = select(ExternalDocumentSourceEvidenceAdmissionExecution).where(
        ExternalDocumentSourceEvidenceAdmissionExecution.id == execution_id,
        ExternalDocumentSourceEvidenceAdmissionExecution.organization_id
        == organization_id,
        ExternalDocumentSourceEvidenceAdmissionExecution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    execution = db.scalar(stmt)
    if execution is None:
        if missing_is_conflict:
            raise ExternalDocumentSourceConflictError(
                "Evidence family binding admission lineage is missing"
            )
        raise ExternalDocumentSourceNotFoundError("Evidence admission execution not found")

    _ensure_execution_integrity(db, execution)
    _active_claim(
        db,
        organization_id=organization_id,
        claim_id=execution.claim_id,
    )
    document = _verify_document_baseline(
        db,
        execution,
        require_uploaded=require_uploaded,
        require_current=require_current,
    )
    observation = _generation_3_observation(db, execution)
    stable_source_item_hash = observation.observed_provider_item_id_hash
    if stable_source_item_hash is None:
        raise ExternalDocumentSourceConflictError(
            "Stable external source-item identity is unavailable"
        )
    return _ResolvedAdmissionLineage(
        legacy_execution_id=execution.id,
        sftp_execution_id=None,
        organization_id=execution.organization_id,
        claim_id=execution.claim_id,
        profile_id=execution.profile_id,
        document=document,
        provider_kind=execution.provider_kind,
        profile_hash=execution.profile_hash,
        stable_source_item_hash=stable_source_item_hash,
        source_projection_hash=execution.fresh_projection_hash,
        source_observation_completion_hash=execution.observation_completion_hash,
        admission_completion_hash=execution.completion_hash,
        admitted_content_sha256=execution.document_file_hash,
        admitted_byte_count=execution.document_file_size_bytes,
        admitted_mime_type_class=execution.fresh_mime_type_class,
        admitted_provider_version_hash=execution.fresh_version_token_hash,
    )


def _resolve_sftp_admission_lineage(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    require_uploaded: bool,
    require_current: bool,
    for_update: bool,
    missing_is_conflict: bool,
) -> _ResolvedAdmissionLineage:
    stmt = select(ExternalDocumentSourceSftpEvidenceAdmissionExecution).where(
        ExternalDocumentSourceSftpEvidenceAdmissionExecution.id == execution_id,
        ExternalDocumentSourceSftpEvidenceAdmissionExecution.organization_id
        == organization_id,
        ExternalDocumentSourceSftpEvidenceAdmissionExecution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    execution = db.scalar(stmt)
    if execution is None:
        if missing_is_conflict:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence family binding admission lineage is missing"
            )
        raise ExternalDocumentSourceNotFoundError(
            "SFTP Evidence admission execution not found"
        )

    _ensure_sftp_execution_integrity(db, execution)
    _active_claim(
        db,
        organization_id=organization_id,
        claim_id=execution.claim_id,
    )
    document = _verify_sftp_document_baseline(
        db,
        execution,
        require_uploaded=require_uploaded,
        require_current=require_current,
    )
    authorization = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.id
            == execution.authorization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence family binding authorization lineage is missing"
        )
    _ensure_sftp_authorization_integrity(db, authorization)
    if (
        authorization.claim_id != execution.claim_id
        or authorization.profile_hash != execution.profile_hash
        or authorization.authorized_projection_hash
        != execution.fresh_projection_hash
        or authorization.observation_completion_hash
        != execution.observation_completion_hash
        or not authorization.authorized_relative_path_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence family binding trusted lineage drifted"
        )

    stable_source_item_hash = _stable_sftp_source_item_hash(
        profile_id=profile_id,
        relative_path_hash=authorization.authorized_relative_path_hash,
    )
    mime_type = document.mime_type[:128] if document.mime_type else None
    return _ResolvedAdmissionLineage(
        legacy_execution_id=None,
        sftp_execution_id=execution.id,
        organization_id=execution.organization_id,
        claim_id=execution.claim_id,
        profile_id=execution.profile_id,
        document=document,
        provider_kind="sftp",
        profile_hash=execution.profile_hash,
        stable_source_item_hash=stable_source_item_hash,
        source_projection_hash=execution.fresh_projection_hash,
        source_observation_completion_hash=execution.observation_completion_hash,
        admission_completion_hash=execution.completion_hash,
        admitted_content_sha256=execution.document_file_hash,
        admitted_byte_count=execution.document_file_size_bytes,
        admitted_mime_type_class=mime_type,
        admitted_provider_version_hash=None,
    )


def _resolve_binding_lineage(
    db: Session,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    *,
    require_uploaded: bool,
    require_current: bool,
    for_update: bool = False,
) -> _ResolvedAdmissionLineage:
    if binding.provider_kind == "sftp":
        if (
            binding.admission_execution_id is not None
            or binding.sftp_admission_execution_id is None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence family binding admission-lineage selector drifted"
            )
        return _resolve_sftp_admission_lineage(
            db,
            organization_id=binding.organization_id,
            profile_id=binding.profile_id,
            execution_id=binding.sftp_admission_execution_id,
            require_uploaded=require_uploaded,
            require_current=require_current,
            for_update=for_update,
            missing_is_conflict=True,
        )

    if binding.provider_kind not in {"sharepoint", "google_drive"}:
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding provider kind is unsupported"
        )
    if (
        binding.admission_execution_id is None
        or binding.sftp_admission_execution_id is not None
    ):
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding admission-lineage selector drifted"
        )
    return _resolve_legacy_admission_lineage(
        db,
        organization_id=binding.organization_id,
        profile_id=binding.profile_id,
        execution_id=binding.admission_execution_id,
        require_uploaded=require_uploaded,
        require_current=require_current,
        for_update=for_update,
        missing_is_conflict=True,
    )


def _generation_3_observation(
    db: Session,
    execution: ExternalDocumentSourceEvidenceAdmissionExecution,
) -> ExternalDocumentSourceGeneration3ChangeDetectionExecution:
    observation = db.scalar(
        select(ExternalDocumentSourceGeneration3ChangeDetectionExecution).where(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.id
            == execution.generation_3_change_detection_execution_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.organization_id
            == execution.organization_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id
            == execution.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding generation-3 lineage is missing"
        )
    if (
        observation.status != "completed"
        or observation.result_status != "unchanged"
        or observation.observed_provider_item_id_hash is None
        or observation.observed_projection_hash is None
        or observation.completion_hash is None
        or observation.observed_item_kind != "file"
        or observation.provider_kind != execution.provider_kind
        or observation.profile_hash != execution.profile_hash
        or observation.observed_projection_hash != execution.fresh_projection_hash
        or observation.observed_version_token_hash != execution.fresh_version_token_hash
        or observation.observed_byte_size != execution.fresh_byte_size
        or observation.observed_mime_type_class != execution.fresh_mime_type_class
        or observation.completion_hash != execution.observation_completion_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding source-item lineage drifted"
        )
    return observation


def _verify_document_baseline(
    db: Session,
    execution: ExternalDocumentSourceEvidenceAdmissionExecution,
    *,
    require_uploaded: bool,
    require_current: bool,
):
    document = _get_document(db, execution)
    if (
        document.id != execution.document_id
        or document.document_family_id != document.id
        or document.version_number != 1
        or document.supersedes_document_id is not None
        or document.file_hash != execution.document_file_hash
        or document.file_size_bytes != execution.document_file_size_bytes
    ):
        raise ExternalDocumentSourceConflictError(
            "Admitted Document is not a valid initial Evidence-family baseline"
        )
    if require_current and not document.is_current:
        raise ExternalDocumentSourceConflictError(
            "Initial Evidence-family baseline must still be current when binding is created"
        )
    if require_uploaded and document.processing_status != DocumentProcessingStatus.UPLOADED:
        raise ExternalDocumentSourceConflictError(
            "Admitted Document baseline was already processed before family binding"
        )
    return document


def _scope_hash(
    lineage: _ResolvedAdmissionLineage,
    *,
    stable_source_item_hash: str,
    document_family_id: UUID,
    request_key: str,
) -> str:
    if lineage.legacy_execution_id is not None:
        payload = {
            "organization_id": str(lineage.organization_id),
            "claim_id": str(lineage.claim_id),
            "profile_id": str(lineage.profile_id),
            "admission_execution_id": str(lineage.legacy_execution_id),
            "admission_completion_hash": lineage.admission_completion_hash,
            "document_id": str(lineage.document.id),
            "document_family_id": str(document_family_id),
            "provider_kind": lineage.provider_kind,
            "profile_hash": lineage.profile_hash,
            "stable_source_item_hash": stable_source_item_hash,
            "source_projection_hash": lineage.source_projection_hash,
            "source_observation_completion_hash": (
                lineage.source_observation_completion_hash
            ),
            "request_key": request_key,
        }
    else:
        payload = {
            "organization_id": str(lineage.organization_id),
            "claim_id": str(lineage.claim_id),
            "profile_id": str(lineage.profile_id),
            "sftp_admission_execution_id": str(lineage.sftp_execution_id),
            "admission_completion_hash": lineage.admission_completion_hash,
            "document_id": str(lineage.document.id),
            "document_family_id": str(document_family_id),
            "provider_kind": lineage.provider_kind,
            "profile_hash": lineage.profile_hash,
            "stable_source_item_hash": stable_source_item_hash,
            "source_projection_hash": lineage.source_projection_hash,
            "source_observation_completion_hash": (
                lineage.source_observation_completion_hash
            ),
            "request_key": request_key,
        }
    return _canonical_hash(payload)


def _request_hash(binding: ExternalDocumentSourceEvidenceFamilyBinding) -> str:
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "bound_by_id": str(binding.bound_by_id),
            "binding_reason": binding.binding_reason,
            "bound_at": _iso(binding.bound_at),
            **_safety(),
        }
    )


def _completion_hash(binding: ExternalDocumentSourceEvidenceFamilyBinding) -> str:
    if binding.provider_kind == "sftp":
        admission_lineage = {
            "sftp_admission_execution_id": str(
                binding.sftp_admission_execution_id
            )
        }
    else:
        admission_lineage = {
            "admission_execution_id": str(binding.admission_execution_id)
        }
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "request_hash": binding.request_hash,
            "status": binding.status,
            **admission_lineage,
            "initial_document_id": str(binding.initial_document_id),
            "document_family_id": str(binding.document_family_id),
            "current_document_id": str(binding.current_document_id),
            "current_version_number": binding.current_version_number,
            "stable_source_item_hash": binding.stable_source_item_hash,
            "source_projection_hash": binding.source_projection_hash,
            "source_observation_completion_hash": binding.source_observation_completion_hash,
            "admission_completion_hash": binding.admission_completion_hash,
            "admitted_content_sha256": binding.admitted_content_sha256,
            "admitted_byte_count": binding.admitted_byte_count,
            "admitted_mime_type_class": binding.admitted_mime_type_class,
            "admitted_provider_version_hash": binding.admitted_provider_version_hash,
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceEvidenceFamilyBindingReceipt) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "binding_id": str(receipt.binding_id),
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
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
) -> list[ExternalDocumentSourceEvidenceFamilyBindingReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceEvidenceFamilyBindingReceipt)
            .where(
                ExternalDocumentSourceEvidenceFamilyBindingReceipt.organization_id
                == binding.organization_id,
                ExternalDocumentSourceEvidenceFamilyBindingReceipt.binding_id
                == binding.id,
            )
            .order_by(
                ExternalDocumentSourceEvidenceFamilyBindingReceipt.sequence_number.asc()
            )
        ).all()
    )


def _ensure_binding_integrity(
    db: Session,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
) -> None:
    _active_claim(
        db,
        organization_id=binding.organization_id,
        claim_id=binding.claim_id,
    )
    lineage = _resolve_binding_lineage(
        db,
        binding,
        require_uploaded=False,
        require_current=False,
    )
    document = lineage.document

    expected = {
        "claim_id": lineage.claim_id,
        "admission_execution_id": lineage.legacy_execution_id,
        "sftp_admission_execution_id": lineage.sftp_execution_id,
        "initial_document_id": document.id,
        "document_family_id": document.document_family_id,
        "current_document_id": document.id,
        "provider_kind": lineage.provider_kind,
        "profile_hash": lineage.profile_hash,
        "stable_source_item_hash": lineage.stable_source_item_hash,
        "source_projection_hash": lineage.source_projection_hash,
        "source_observation_completion_hash": (
            lineage.source_observation_completion_hash
        ),
        "admission_completion_hash": lineage.admission_completion_hash,
        "current_version_number": 1,
        "admitted_content_sha256": lineage.admitted_content_sha256,
        "admitted_byte_count": lineage.admitted_byte_count,
        "admitted_mime_type_class": lineage.admitted_mime_type_class,
        "admitted_provider_version_hash": lineage.admitted_provider_version_hash,
        "status": "active",
    }
    for field, expected_value in expected.items():
        if getattr(binding, field) != expected_value:
            raise ExternalDocumentSourceConflictError(
                f"Evidence family binding integrity drifted at {field}"
            )

    expected_scope = _scope_hash(
        lineage,
        stable_source_item_hash=lineage.stable_source_item_hash,
        document_family_id=document.document_family_id,
        request_key=binding.request_key,
    )
    if binding.scope_hash != expected_scope:
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding scope integrity failed"
        )
    if binding.request_hash != _request_hash(binding):
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding request integrity failed"
        )
    if binding.completion_hash != _completion_hash(binding):
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding completion integrity failed"
        )
    for field, expected_value in _safety().items():
        if bool(getattr(binding, field)) != expected_value:
            raise ExternalDocumentSourceConflictError(
                "Evidence family binding safety boundary drifted"
            )

    rows = _receipts(db, binding)
    if len(rows) != 1:
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding receipt lifecycle drifted"
        )
    receipt = rows[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "bound"
        or receipt.status_after != "active"
        or receipt.actor_id != binding.bound_by_id
        or _aware(receipt.occurred_at) != _aware(binding.bound_at)
        or receipt.reason != binding.binding_reason
        or receipt.scope_hash != binding.scope_hash
        or receipt.decision_hash != binding.completion_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding receipt integrity drifted"
        )
    for field, expected_value in _safety().items():
        if bool(getattr(receipt, field)) != expected_value:
            raise ExternalDocumentSourceConflictError(
                "Evidence family binding receipt safety boundary drifted"
            )


def bind_external_document_source_evidence_family(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    bound_by_id: UUID,
    request_key: str,
    binding_reason: str,
    admission_execution_id: UUID | None = None,
    sftp_admission_execution_id: UUID | None = None,
) -> tuple[ExternalDocumentSourceEvidenceFamilyBinding, str]:
    if (admission_execution_id is None) == (sftp_admission_execution_id is None):
        raise ExternalDocumentSourceValidationError(
            "Exactly one Evidence admission execution lineage must be supplied"
        )

    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        binding_reason,
        field="reason",
        minimum=20,
        maximum=2000,
    )

    existing_request = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding).where(
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id == profile_id,
            ExternalDocumentSourceEvidenceFamilyBinding.request_key == normalized_key,
        )
    )
    if existing_request is not None:
        _ensure_binding_integrity(db, existing_request)
        if (
            existing_request.admission_execution_id != admission_execution_id
            or existing_request.sftp_admission_execution_id
            != sftp_admission_execution_id
            or existing_request.bound_by_id != bound_by_id
            or existing_request.binding_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Evidence family binding request key was already used with different inputs"
            )
        return existing_request, "replayed"

    if sftp_admission_execution_id is not None:
        lineage = _resolve_sftp_admission_lineage(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            execution_id=sftp_admission_execution_id,
            require_uploaded=True,
            require_current=True,
            for_update=True,
            missing_is_conflict=False,
        )
        execution_field = (
            ExternalDocumentSourceEvidenceFamilyBinding.sftp_admission_execution_id
        )
        execution_value = sftp_admission_execution_id
    else:
        assert admission_execution_id is not None
        lineage = _resolve_legacy_admission_lineage(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            execution_id=admission_execution_id,
            require_uploaded=True,
            require_current=True,
            for_update=True,
            missing_is_conflict=False,
        )
        execution_field = ExternalDocumentSourceEvidenceFamilyBinding.admission_execution_id
        execution_value = admission_execution_id

    existing_execution = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding)
        .where(execution_field == execution_value)
        .with_for_update()
    )
    if existing_execution is not None:
        _ensure_binding_integrity(db, existing_execution)
        raise ExternalDocumentSourceConflictError(
            "Evidence admission execution is already bound to an Evidence family"
        )

    document = lineage.document
    stable_source_item_hash = lineage.stable_source_item_hash

    existing_source = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding)
        .where(
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.claim_id == lineage.claim_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id == profile_id,
            ExternalDocumentSourceEvidenceFamilyBinding.stable_source_item_hash
            == stable_source_item_hash,
        )
        .with_for_update()
    )
    if existing_source is not None:
        _ensure_binding_integrity(db, existing_source)
        raise ExternalDocumentSourceConflictError(
            "External source item is already bound to an Evidence family"
        )

    existing_family = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding)
        .where(
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.claim_id == lineage.claim_id,
            ExternalDocumentSourceEvidenceFamilyBinding.document_family_id
            == document.document_family_id,
        )
        .with_for_update()
    )
    if existing_family is not None:
        _ensure_binding_integrity(db, existing_family)
        raise ExternalDocumentSourceConflictError(
            "Document family is already bound to an external source item"
        )

    bound_at = _utc_now()
    binding = ExternalDocumentSourceEvidenceFamilyBinding(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=lineage.claim_id,
        profile_id=profile_id,
        admission_execution_id=lineage.legacy_execution_id,
        sftp_admission_execution_id=lineage.sftp_execution_id,
        initial_document_id=document.id,
        document_family_id=document.document_family_id,
        current_document_id=document.id,
        provider_kind=lineage.provider_kind,
        profile_hash=lineage.profile_hash,
        stable_source_item_hash=stable_source_item_hash,
        source_projection_hash=lineage.source_projection_hash,
        source_observation_completion_hash=(
            lineage.source_observation_completion_hash
        ),
        admission_completion_hash=lineage.admission_completion_hash,
        current_version_number=1,
        admitted_content_sha256=lineage.admitted_content_sha256,
        admitted_byte_count=lineage.admitted_byte_count,
        admitted_mime_type_class=lineage.admitted_mime_type_class,
        admitted_provider_version_hash=lineage.admitted_provider_version_hash,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="active",
        bound_by_id=bound_by_id,
        binding_reason=normalized_reason,
        bound_at=bound_at,
        completion_hash="",
        **_safety(),
    )
    binding.scope_hash = _scope_hash(
        lineage,
        stable_source_item_hash=stable_source_item_hash,
        document_family_id=document.document_family_id,
        request_key=normalized_key,
    )
    binding.request_hash = _request_hash(binding)
    binding.completion_hash = _completion_hash(binding)
    db.add(binding)
    db.flush()

    receipt = ExternalDocumentSourceEvidenceFamilyBindingReceipt(
        id=uuid4(),
        organization_id=organization_id,
        binding_id=binding.id,
        sequence_number=1,
        event_type="bound",
        status_after="active",
        actor_id=bound_by_id,
        occurred_at=bound_at,
        reason=normalized_reason,
        scope_hash=binding.scope_hash,
        decision_hash=binding.completion_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    _ensure_binding_integrity(db, binding)

    admission_lineage_audit = {}
    if lineage.legacy_execution_id is not None:
        admission_lineage_audit["admission_execution_id"] = str(
            lineage.legacy_execution_id
        )
    if lineage.sftp_execution_id is not None:
        admission_lineage_audit["sftp_admission_execution_id"] = str(
            lineage.sftp_execution_id
        )

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=bound_by_id,
        action="BIND_EXTERNAL_DOCUMENT_SOURCE_EVIDENCE_FAMILY",
        entity_type="document",
        entity_id=document.id,
        new_values={
            "claim_id": str(lineage.claim_id),
            "profile_id": str(profile_id),
            "evidence_family_binding_id": str(binding.id),
            **admission_lineage_audit,
            "document_id": str(document.id),
            "document_family_id": str(document.document_family_id),
            "current_version_number": 1,
            "provider_kind": lineage.provider_kind,
            "stable_source_item_hash": stable_source_item_hash,
            "admitted_content_sha256": lineage.admitted_content_sha256,
            "admitted_byte_count": lineage.admitted_byte_count,
            "processing_enqueued": False,
        },
        details=(
            "A verified external Evidence admission was bound to a durable "
            "provider-neutral source-item/Document-family baseline. No provider, "
            "storage, Document, processing, OCR, AI, Claim or checkpoint mutation "
            "authority was exercised."
        ),
    )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ExternalDocumentSourceConflictError(
            "Evidence family binding could not be committed safely"
        ) from exc
    db.refresh(binding)
    return binding, "bound"


def get_external_document_source_evidence_family_binding(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> ExternalDocumentSourceEvidenceFamilyBinding:
    binding = db.scalar(
        select(ExternalDocumentSourceEvidenceFamilyBinding).where(
            ExternalDocumentSourceEvidenceFamilyBinding.id == binding_id,
            ExternalDocumentSourceEvidenceFamilyBinding.organization_id
            == organization_id,
            ExternalDocumentSourceEvidenceFamilyBinding.profile_id == profile_id,
        )
    )
    if binding is None:
        raise ExternalDocumentSourceNotFoundError(
            "Evidence family binding not found"
        )
    _ensure_binding_integrity(db, binding)
    return binding


def list_external_document_source_evidence_family_binding_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> list[ExternalDocumentSourceEvidenceFamilyBindingReceipt]:
    binding = get_external_document_source_evidence_family_binding(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    return _receipts(db, binding)
