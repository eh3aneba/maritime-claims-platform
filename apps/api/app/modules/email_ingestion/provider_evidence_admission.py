from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.malware import MalwareScannerError, MalwareScanVerdict, scan_file
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
)
from app.modules.documents.service import (
    _storage,
    make_storage_key,
    normalize_original_filename,
    validate_file_signature,
    validate_upload,
)
from app.modules.documents.storage import StorageError
from app.modules.email_ingestion.models import (
    EmailAttachmentManifest,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailMessageStatus,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.users.models import User

settings = get_settings()


def _document_response(document: Document, *, replayed: bool) -> dict:
    return {"document": document, "replayed": replayed}


def _record_admission_failure(
    db: Session,
    *,
    manifest: EmailAttachmentManifest,
    user: User,
    code: str,
    details: str,
) -> None:
    now = datetime.now(UTC)
    manifest.evidence_admission_attempted_at = now
    manifest.evidence_admission_failure_code = code
    write_audit_log(
        db,
        organization_id=manifest.organization_id,
        user_id=user.id,
        action="REJECT_EMAIL_ATTACHMENT_EVIDENCE_ADMISSION",
        entity_type="email_attachment_manifest",
        entity_id=manifest.id,
        new_values={
            "failure_code": code,
            "message_id": str(manifest.message_id),
            "admission_status": manifest.admission_status,
        },
        details=details,
    )
    db.commit()


def _mark_quarantine_integrity_failure(
    db: Session,
    *,
    manifest: EmailAttachmentManifest,
    user: User,
    code: str,
) -> None:
    manifest.quarantine_key = None
    manifest.admission_status = "acquisition_failed"
    manifest.acquisition_failure_code = "provider_attachment_quarantine_integrity_mismatch"
    _record_admission_failure(
        db,
        manifest=manifest,
        user=user,
        code=code,
        details=(
            "Provider Evidence admission failed closed because quarantine integrity could not be proven. "
            "No provider locator, credential, filename, storage key, hash, message content or attachment bytes logged."
        ),
    )


def _hash_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _active_provider_source(
    db: Session,
    *,
    message: IngestedEmailMessage,
    organization_id: UUID,
) -> tuple[EmailProviderAdapter, EmailIngestionConnection]:
    if message.adapter_id is None:
        raise HTTPException(409, "Legacy connection-only email has no provider Evidence-admission authority")
    adapter = db.scalar(
        select(EmailProviderAdapter).where(
            EmailProviderAdapter.id == message.adapter_id,
            EmailProviderAdapter.organization_id == organization_id,
        )
    )
    connection = db.scalar(
        select(EmailIngestionConnection).where(
            EmailIngestionConnection.id == message.connection_id,
            EmailIngestionConnection.organization_id == organization_id,
        )
    )
    if adapter is None or connection is None:
        raise HTTPException(404, "Provider source not found")
    if adapter.provider_kind not in {"microsoft_graph", "gmail_api"}:
        raise HTTPException(409, "This provider kind has no Evidence-admission authority")
    if adapter.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both remain active")
    return adapter, connection


def admit_provider_attachment_to_evidence(
    db: Session,
    *,
    message: IngestedEmailMessage,
    manifest: EmailAttachmentManifest,
    user: User,
    confirm_admission: bool,
    admission_note: str,
    document_type: str | None,
    confidentiality_level: ConfidentialityLevel,
) -> dict:
    existing = db.scalar(
        select(Document).where(
            Document.organization_id == user.organization_id,
            Document.source_email_attachment_manifest_id == manifest.id,
        )
    )
    if existing is not None:
        if existing.deleted_at is not None:
            raise HTTPException(409, "This provider attachment was already admitted to a deleted Evidence record")
        return _document_response(existing, replayed=True)

    if not confirm_admission:
        raise HTTPException(422, "Explicit Evidence admission confirmation is required")
    admission_note = admission_note.strip()
    if len(admission_note) < 20:
        raise HTTPException(422, "An Evidence admission note of at least 20 characters is required")
    if message.status != EmailMessageStatus.LINKED or message.linked_claim_id is None:
        raise HTTPException(409, "Evidence admission requires a human-linked email claim context")
    if manifest.acquired_claim_id is None or manifest.acquired_claim_id != message.linked_claim_id:
        raise HTTPException(409, "Acquired provider bytes are not bound to the linked claim")
    if manifest.admission_status != "clean_pending_human_admission":
        raise HTTPException(409, "Only clean provider quarantine may be admitted to Evidence")
    if manifest.malware_scan_status != "clean" or manifest.malware_scanned_at is None:
        raise HTTPException(409, "A successful provider quarantine malware scan is required")
    if not manifest.quarantine_key or not manifest.acquired_file_hash or manifest.acquired_file_size_bytes is None:
        raise HTTPException(409, "Provider quarantine provenance is incomplete")

    _active_provider_source(db, message=message, organization_id=user.organization_id)
    claim = db.scalar(
        select(Claim).where(
            Claim.id == message.linked_claim_id,
            Claim.organization_id == user.organization_id,
        )
    )
    if claim is None:
        raise HTTPException(404, "Claim not found")

    storage = _storage()
    quarantine_key = manifest.quarantine_key
    try:
        quarantine_path = storage.path_for(quarantine_key)
    except FileNotFoundError as exc:
        _mark_quarantine_integrity_failure(
            db,
            manifest=manifest,
            user=user,
            code="evidence_admission_quarantine_missing",
        )
        raise HTTPException(409, "Provider quarantine bytes are unavailable; reacquisition is required") from exc

    actual_hash, actual_size = _hash_and_size(quarantine_path)
    if actual_hash != manifest.acquired_file_hash or actual_size != manifest.acquired_file_size_bytes:
        storage.delete_physical(quarantine_key)
        _mark_quarantine_integrity_failure(
            db,
            manifest=manifest,
            user=user,
            code="evidence_admission_quarantine_integrity_mismatch",
        )
        raise HTTPException(409, "Provider quarantine integrity changed; reacquisition is required")

    original_filename = normalize_original_filename(manifest.filename)
    try:
        suffix = validate_upload(original_filename, manifest.mime_type)
        validate_file_signature(storage, quarantine_key, suffix)
    except HTTPException as exc:
        _mark_quarantine_integrity_failure(
            db,
            manifest=manifest,
            user=user,
            code="evidence_admission_signature_rejected",
        )
        raise HTTPException(exc.status_code, "Provider quarantine signature validation failed") from exc

    duplicate = db.scalar(
        select(Document).where(
            Document.organization_id == user.organization_id,
            Document.claim_id == claim.id,
            Document.file_hash == actual_hash,
        )
    )
    if duplicate is not None:
        _record_admission_failure(
            db,
            manifest=manifest,
            user=user,
            code="evidence_admission_duplicate_claim_bytes",
            details=(
                "Evidence admission was rejected because identical bytes already exist as a different claim Document. "
                "No provider locator, credential, filename, storage key, hash, message content or attachment bytes logged."
            ),
        )
        raise HTTPException(409, f"These bytes already exist in the claim as Document {duplicate.id}")

    if not settings.malware_scan_enabled:
        _record_admission_failure(
            db,
            manifest=manifest,
            user=user,
            code="evidence_admission_scanner_disabled",
            details="Evidence admission requires an authoritative malware scan immediately before filing.",
        )
        raise HTTPException(503, "Evidence admission requires malware scanning")

    attempted_at = datetime.now(UTC)
    manifest.evidence_admission_attempted_at = attempted_at
    try:
        scan_result = scan_file(
            quarantine_path,
            host=settings.clamav_host,
            port=settings.clamav_port,
            timeout_seconds=settings.clamav_timeout_seconds,
        )
    except MalwareScannerError as exc:
        manifest.evidence_admission_failure_code = "evidence_admission_scan_error"
        write_audit_log(
            db,
            organization_id=manifest.organization_id,
            user_id=user.id,
            action="REJECT_EMAIL_ATTACHMENT_EVIDENCE_ADMISSION",
            entity_type="email_attachment_manifest",
            entity_id=manifest.id,
            new_values={
                "failure_code": "evidence_admission_scan_error",
                "message_id": str(message.id),
                "admission_status": manifest.admission_status,
            },
            details="Admission-time malware scanning was unavailable; provider bytes remain quarantined.",
        )
        db.commit()
        raise HTTPException(503, "Admission-time malware scanning could not complete") from exc

    if scan_result.verdict == MalwareScanVerdict.INFECTED:
        manifest.malware_scan_status = "infected"
        manifest.malware_scanned_at = attempted_at
        manifest.admission_status = "infected_quarantined"
        manifest.evidence_admission_failure_code = "evidence_admission_infected"
        write_audit_log(
            db,
            organization_id=manifest.organization_id,
            user_id=user.id,
            action="REJECT_EMAIL_ATTACHMENT_EVIDENCE_ADMISSION",
            entity_type="email_attachment_manifest",
            entity_id=manifest.id,
            new_values={
                "failure_code": "evidence_admission_infected",
                "message_id": str(message.id),
                "admission_status": manifest.admission_status,
            },
            details="Admission-time malware scan rejected the provider bytes; no Evidence Document was created.",
        )
        db.commit()
        raise HTTPException(422, "Malware was detected during Evidence admission; bytes remain quarantined")

    document_id = uuid4()
    storage_key = make_storage_key(
        organization_id=user.organization_id,
        claim_id=claim.id,
        document_id=document_id,
        suffix=suffix,
    )
    try:
        storage.promote(quarantine_key, storage_key)
    except StorageError as exc:
        _record_admission_failure(
            db,
            manifest=manifest,
            user=user,
            code="evidence_admission_storage_promotion_error",
            details="Canonical Evidence storage promotion failed; provider bytes remain quarantined.",
        )
        raise HTTPException(503, "Canonical Evidence storage promotion failed") from exc

    document = Document(
        id=document_id,
        organization_id=user.organization_id,
        claim_id=claim.id,
        uploaded_by_id=user.id,
        source_email_attachment_manifest_id=manifest.id,
        source_admission_note=admission_note[:1000],
        document_family_id=document_id,
        filename=original_filename,
        original_filename=original_filename,
        document_type=(document_type.strip()[:100] or None) if document_type else None,
        mime_type=manifest.mime_type[:150],
        file_size_bytes=actual_size,
        file_hash=actual_hash,
        storage_key=storage_key,
        confidentiality_level=confidentiality_level,
        malware_scan_status=DocumentMalwareScanStatus.CLEAN,
        malware_scanned_at=attempted_at,
    )
    db.add(document)
    manifest.quarantine_key = None
    manifest.admission_status = "admitted_to_evidence"
    manifest.evidence_admission_failure_code = None

    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="ADMIT_EMAIL_ATTACHMENT_TO_EVIDENCE",
        entity_type="document",
        entity_id=document.id,
        new_values={
            "claim_id": str(claim.id),
            "document_id": str(document.id),
            "source_email_attachment_manifest_id": str(manifest.id),
            "document_type": document.document_type,
            "confidentiality_level": document.confidentiality_level.value,
            "admission_status": manifest.admission_status,
            "admission_note": document.source_admission_note,
            "file_size_bytes": actual_size,
            "malware_scan_status": document.malware_scan_status.value,
            "processing_enqueued": False,
        },
        details=(
            "A human explicitly admitted previously quarantined provider bytes into canonical Evidence after "
            "fresh integrity and malware verification. No text extraction, OCR, AI or claim decision workflow was started."
        ),
    )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        restored = False
        try:
            storage.promote(storage_key, quarantine_key)
            restored = True
        except StorageError:
            storage.delete_physical(storage_key)
        if not restored:
            recovered = db.get(EmailAttachmentManifest, manifest.id)
            if recovered is not None:
                recovered.quarantine_key = None
                recovered.admission_status = "acquisition_failed"
                recovered.acquisition_failure_code = "provider_attachment_quarantine_integrity_mismatch"
                recovered.evidence_admission_failure_code = "evidence_admission_commit_recovery_failed"
                recovered.evidence_admission_attempted_at = datetime.now(UTC)
                db.commit()
        raise HTTPException(409, "Evidence admission could not be committed safely") from exc

    db.refresh(document)
    return _document_response(document, replayed=False)
