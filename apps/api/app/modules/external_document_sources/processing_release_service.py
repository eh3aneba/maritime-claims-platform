from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    get_external_document_source_evidence_family_binding,
)
from app.modules.external_document_sources.processing_release_models import (
    ExternalDocumentSourceProcessingRelease,
    ExternalDocumentSourceProcessingReleaseReceipt,
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
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _safety() -> dict[str, bool]:
    return {
        "family_binding_verified": True,
        "current_document_verified": True,
        "local_text_processing_authorized": True,
        "ai_processing_authorized": False,
        "provider_io_performed": False,
        "storage_io_performed": False,
        "document_mutated": False,
        "processing_enqueued": False,
        "claim_mutated": False,
    }


def _binding_for_document(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lock: bool,
) -> ExternalDocumentSourceEvidenceFamilyBinding:
    stmt = select(ExternalDocumentSourceEvidenceFamilyBinding).where(
        ExternalDocumentSourceEvidenceFamilyBinding.organization_id == organization_id,
        ExternalDocumentSourceEvidenceFamilyBinding.claim_id == claim_id,
        ExternalDocumentSourceEvidenceFamilyBinding.current_document_id == document_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    binding = db.scalar(stmt)
    if binding is None:
        raise ExternalDocumentSourceNotFoundError(
            "External Evidence family binding not found for this Document"
        )
    return get_external_document_source_evidence_family_binding(
        db,
        organization_id=organization_id,
        profile_id=binding.profile_id,
        binding_id=binding.id,
    )


def _verify_exact_current_document(
    db: Session,
    *,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    require_uploaded: bool,
) -> Document:
    document = db.get(Document, binding.current_document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.organization_id != binding.organization_id
        or document.claim_id != binding.claim_id
        or document.id != binding.current_document_id
        or document.document_family_id != binding.document_family_id
        or document.version_number != binding.current_version_number
        or not document.is_current
    ):
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release requires the exact current Document version"
        )
    if require_uploaded and document.processing_status != DocumentProcessingStatus.UPLOADED:
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release can only be granted before local processing starts"
        )
    return document


def _scope_hash(
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    *,
    document: Document,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(binding.organization_id),
            "claim_id": str(binding.claim_id),
            "profile_id": str(binding.profile_id),
            "binding_id": str(binding.id),
            "binding_completion_hash": binding.completion_hash,
            "document_family_id": str(document.document_family_id),
            "document_id": str(document.id),
            "document_version_number": document.version_number,
            "request_key": request_key,
            "local_text_processing_authorized": True,
            "ai_processing_authorized": False,
        }
    )


def _request_hash(release: ExternalDocumentSourceProcessingRelease) -> str:
    return _canonical_hash(
        {
            "release_id": str(release.id),
            "scope_hash": release.scope_hash,
            "released_by_id": str(release.released_by_id),
            "release_reason": release.release_reason,
            "released_at": _iso(release.released_at),
            **_safety(),
        }
    )


def _completion_hash(release: ExternalDocumentSourceProcessingRelease) -> str:
    return _canonical_hash(
        {
            "release_id": str(release.id),
            "scope_hash": release.scope_hash,
            "request_hash": release.request_hash,
            "status": "active",
            "binding_id": str(release.binding_id),
            "document_family_id": str(release.document_family_id),
            "document_id": str(release.document_id),
            "document_version_number": release.document_version_number,
            **_safety(),
        }
    )


def _terminal_hash(release: ExternalDocumentSourceProcessingRelease) -> str:
    return _canonical_hash(
        {
            "release_id": str(release.id),
            "completion_hash": release.completion_hash,
            "status": "revoked",
            "revocation_request_key": release.revocation_request_key,
            "revoked_by_id": str(release.revoked_by_id),
            "revocation_reason": release.revocation_reason,
            "revoked_at": _iso(release.revoked_at),
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceProcessingReleaseReceipt) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
            "organization_id": str(receipt.organization_id),
            "release_id": str(receipt.release_id),
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
    release: ExternalDocumentSourceProcessingRelease,
) -> list[ExternalDocumentSourceProcessingReleaseReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceProcessingReleaseReceipt)
            .where(
                ExternalDocumentSourceProcessingReleaseReceipt.organization_id
                == release.organization_id,
                ExternalDocumentSourceProcessingReleaseReceipt.release_id == release.id,
            )
            .order_by(ExternalDocumentSourceProcessingReleaseReceipt.sequence_number.asc())
        ).all()
    )


def ensure_processing_release_integrity(
    db: Session,
    release: ExternalDocumentSourceProcessingRelease,
) -> None:
    binding = get_external_document_source_evidence_family_binding(
        db,
        organization_id=release.organization_id,
        profile_id=release.profile_id,
        binding_id=release.binding_id,
    )
    document = _verify_exact_current_document(
        db,
        binding=binding,
        require_uploaded=False,
    )
    expected = {
        "claim_id": binding.claim_id,
        "profile_id": binding.profile_id,
        "document_family_id": binding.document_family_id,
        "document_id": document.id,
        "document_version_number": document.version_number,
    }
    for field, value in expected.items():
        if getattr(release, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"External Evidence processing release integrity drifted at {field}"
            )

    expected_scope = _scope_hash(binding, document=document, request_key=release.request_key)
    if release.scope_hash != expected_scope:
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release scope integrity failed"
        )
    if release.request_hash != _request_hash(release):
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release request integrity failed"
        )
    if release.completion_hash != _completion_hash(release):
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release completion integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(release, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "External Evidence processing release safety boundary drifted"
            )

    receipts = _receipts(db, release)
    expected_count = 1 if release.status == "active" else 2
    if len(receipts) != expected_count:
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release receipt lifecycle drifted"
        )
    first = receipts[0]
    if (
        first.sequence_number != 1
        or first.event_type != "granted"
        or first.status_after != "active"
        or first.actor_id != release.released_by_id
        or _aware(first.occurred_at) != _aware(release.released_at)
        or first.reason != release.release_reason
        or first.scope_hash != release.scope_hash
        or first.decision_hash != release.completion_hash
        or first.prior_receipt_hash is not None
        or first.receipt_hash != _receipt_hash(first)
    ):
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release grant receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(first, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "External Evidence processing release grant safety boundary drifted"
            )

    if release.status == "active":
        if any(
            value is not None
            for value in (
                release.revocation_request_key,
                release.revoked_by_id,
                release.revocation_reason,
                release.revoked_at,
                release.terminal_hash,
            )
        ):
            raise ExternalDocumentSourceConflictError(
                "External Evidence processing release active state drifted"
            )
        return

    if release.status != "revoked" or release.terminal_hash != _terminal_hash(release):
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release terminal integrity failed"
        )
    second = receipts[1]
    if (
        second.sequence_number != 2
        or second.event_type != "revoked"
        or second.status_after != "revoked"
        or second.actor_id != release.revoked_by_id
        or _aware(second.occurred_at) != _aware(release.revoked_at)
        or second.reason != release.revocation_reason
        or second.scope_hash != release.scope_hash
        or second.decision_hash != release.terminal_hash
        or second.prior_receipt_hash != first.receipt_hash
        or second.receipt_hash != _receipt_hash(second)
    ):
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release revocation receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(second, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "External Evidence processing release revocation safety boundary drifted"
            )


def get_processing_release_for_document(
    db: Session,
    *,
    document: Document,
) -> ExternalDocumentSourceProcessingRelease | None:
    release = db.scalar(
        select(ExternalDocumentSourceProcessingRelease).where(
            ExternalDocumentSourceProcessingRelease.organization_id == document.organization_id,
            ExternalDocumentSourceProcessingRelease.claim_id == document.claim_id,
            ExternalDocumentSourceProcessingRelease.document_id == document.id,
        )
    )
    if release is None:
        return None
    ensure_processing_release_integrity(db, release)
    return release


def get_active_processing_release_for_document(
    db: Session,
    *,
    document: Document,
) -> ExternalDocumentSourceProcessingRelease | None:
    release = get_processing_release_for_document(db, document=document)
    if release is None or release.status != "active":
        return None
    return release


def grant_processing_release(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    released_by_id: UUID,
    request_key: str,
    reason: str,
) -> tuple[ExternalDocumentSourceProcessingRelease, str]:
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(reason, field="reason", minimum=20, maximum=2000)

    existing_request = db.scalar(
        select(ExternalDocumentSourceProcessingRelease).where(
            ExternalDocumentSourceProcessingRelease.organization_id == organization_id,
            ExternalDocumentSourceProcessingRelease.request_key == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_processing_release_integrity(db, existing_request)
        if (
            existing_request.claim_id != claim_id
            or existing_request.document_id != document_id
            or existing_request.released_by_id != released_by_id
            or existing_request.release_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "External Evidence processing release request key was already used with different inputs"
            )
        return existing_request, "replayed"

    binding = _binding_for_document(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lock=True,
    )
    document = _verify_exact_current_document(
        db,
        binding=binding,
        require_uploaded=True,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceProcessingRelease)
        .where(
            ExternalDocumentSourceProcessingRelease.organization_id == organization_id,
            ExternalDocumentSourceProcessingRelease.binding_id == binding.id,
            ExternalDocumentSourceProcessingRelease.document_id == document.id,
            ExternalDocumentSourceProcessingRelease.document_version_number
            == document.version_number,
        )
        .with_for_update()
    )
    if existing is not None:
        ensure_processing_release_integrity(db, existing)
        raise ExternalDocumentSourceConflictError(
            "This exact external Evidence version already has a processing release lifecycle"
        )

    released_at = _utc_now()
    release = ExternalDocumentSourceProcessingRelease(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=claim_id,
        profile_id=binding.profile_id,
        binding_id=binding.id,
        document_family_id=binding.document_family_id,
        document_id=document.id,
        document_version_number=document.version_number,
        request_key=normalized_key,
        scope_hash="",
        request_hash="",
        status="active",
        released_by_id=released_by_id,
        release_reason=normalized_reason,
        released_at=released_at,
        completion_hash="",
        **_safety(),
    )
    release.scope_hash = _scope_hash(binding, document=document, request_key=normalized_key)
    release.request_hash = _request_hash(release)
    release.completion_hash = _completion_hash(release)
    db.add(release)
    db.flush()

    receipt = ExternalDocumentSourceProcessingReleaseReceipt(
        id=uuid4(),
        organization_id=organization_id,
        release_id=release.id,
        sequence_number=1,
        event_type="granted",
        status_after="active",
        actor_id=released_by_id,
        occurred_at=released_at,
        reason=normalized_reason,
        scope_hash=release.scope_hash,
        decision_hash=release.completion_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    ensure_processing_release_integrity(db, release)

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=released_by_id,
        action="RELEASE_EXTERNAL_EVIDENCE_FOR_LOCAL_PROCESSING",
        entity_type="document",
        entity_id=document.id,
        new_values={
            "claim_id": str(claim_id),
            "processing_release_id": str(release.id),
            "evidence_family_binding_id": str(binding.id),
            "document_family_id": str(binding.document_family_id),
            "document_id": str(document.id),
            "document_version_number": document.version_number,
            "local_text_processing_authorized": True,
            "ai_processing_authorized": False,
            "processing_enqueued": False,
        },
        details=(
            "A human-controlled exact-current release authorized local Evidence processing only. "
            "No provider/storage I/O, processing enqueue, Document mutation, Claim mutation or AI "
            "authorization was performed by the release itself."
        ),
    )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release could not be committed safely"
        ) from exc
    db.refresh(release)
    return release, "granted"


def revoke_processing_release(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    revoked_by_id: UUID,
    request_key: str,
    reason: str,
) -> tuple[ExternalDocumentSourceProcessingRelease, str]:
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(reason, field="reason", minimum=20, maximum=2000)

    release = db.scalar(
        select(ExternalDocumentSourceProcessingRelease)
        .where(
            ExternalDocumentSourceProcessingRelease.organization_id == organization_id,
            ExternalDocumentSourceProcessingRelease.claim_id == claim_id,
            ExternalDocumentSourceProcessingRelease.document_id == document_id,
        )
        .with_for_update()
    )
    if release is None:
        raise ExternalDocumentSourceNotFoundError(
            "External Evidence processing release not found"
        )
    ensure_processing_release_integrity(db, release)

    if release.status == "revoked":
        if (
            release.revocation_request_key == normalized_key
            and release.revoked_by_id == revoked_by_id
            and release.revocation_reason == normalized_reason
        ):
            return release, "replayed"
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release is already revoked"
        )

    release.status = "revoked"
    release.revocation_request_key = normalized_key
    release.revoked_by_id = revoked_by_id
    release.revocation_reason = normalized_reason
    release.revoked_at = _utc_now()
    release.terminal_hash = _terminal_hash(release)

    first = _receipts(db, release)[0]
    receipt = ExternalDocumentSourceProcessingReleaseReceipt(
        id=uuid4(),
        organization_id=organization_id,
        release_id=release.id,
        sequence_number=2,
        event_type="revoked",
        status_after="revoked",
        actor_id=revoked_by_id,
        occurred_at=release.revoked_at,
        reason=normalized_reason,
        scope_hash=release.scope_hash,
        decision_hash=release.terminal_hash,
        prior_receipt_hash=first.receipt_hash,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    ensure_processing_release_integrity(db, release)

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=revoked_by_id,
        action="REVOKE_EXTERNAL_EVIDENCE_LOCAL_PROCESSING_RELEASE",
        entity_type="document",
        entity_id=document_id,
        new_values={
            "processing_release_id": str(release.id),
            "status": "revoked",
            "local_text_processing_authorized": False,
            "ai_processing_authorized": False,
        },
    )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ExternalDocumentSourceConflictError(
            "External Evidence processing release revocation could not be committed safely"
        ) from exc
    db.refresh(release)
    return release, "revoked"


def list_processing_release_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> list[ExternalDocumentSourceProcessingReleaseReceipt]:
    release = db.scalar(
        select(ExternalDocumentSourceProcessingRelease).where(
            ExternalDocumentSourceProcessingRelease.organization_id == organization_id,
            ExternalDocumentSourceProcessingRelease.claim_id == claim_id,
            ExternalDocumentSourceProcessingRelease.document_id == document_id,
        )
    )
    if release is None:
        raise ExternalDocumentSourceNotFoundError(
            "External Evidence processing release not found"
        )
    ensure_processing_release_integrity(db, release)
    return _receipts(db, release)
