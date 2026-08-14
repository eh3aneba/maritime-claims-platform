from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.malware import MalwareScannerError, MalwareScanVerdict, scan_file
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    QuarantinedUpload,
    QuarantineStatus,
)
from app.modules.documents.service import _storage, make_quarantine_key, make_storage_key
from app.modules.documents.storage import StorageError
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.users.models import User

settings = get_settings()


class EvidenceSecurityError(RuntimeError):
    """Raised when an operator action cannot safely change evidence state."""


@dataclass(frozen=True)
class RescanOutcome:
    status: DocumentMalwareScanStatus
    quarantined_upload_id: UUID | None = None
    threat_name: str | None = None


def _scan_path(path: Path):
    if not settings.malware_scan_enabled:
        raise EvidenceSecurityError("Malware scanning is disabled; rescan is not permitted.")
    return scan_file(
        path,
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout_seconds=settings.clamav_timeout_seconds,
    )


def _logical_and_physical_quarantine(
    db: Session,
    *,
    document: Document,
    requested_by_id: UUID | None,
    quarantine_status: QuarantineStatus,
    threat_name: str | None = None,
    scan_error: str | None = None,
) -> QuarantinedUpload:
    storage = _storage()
    upload_id = uuid4()
    suffix = Path(document.storage_key).suffix or Path(document.original_filename).suffix.lower()
    quarantine_key = make_quarantine_key(
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        upload_id=upload_id,
        suffix=suffix,
    )
    try:
        storage.promote(document.storage_key, quarantine_key)
    except StorageError:
        # Logical quarantine still blocks every download/processing path. Keeping the
        # current physical key allows a later operator retry instead of losing bytes.
        quarantine_key = document.storage_key

    now = datetime.now(UTC)
    quarantined = QuarantinedUpload(
        id=upload_id,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        uploaded_by_id=document.uploaded_by_id,
        source_document_id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        file_hash=document.file_hash,
        quarantine_key=quarantine_key,
        status=quarantine_status,
        threat_name=threat_name,
        scan_error=scan_error,
        scanned_at=now,
        confidentiality_level=document.confidentiality_level,
    )
    db.add(quarantined)
    document.malware_scan_status = (
        DocumentMalwareScanStatus.INFECTED_QUARANTINED
        if quarantine_status == QuarantineStatus.INFECTED
        else DocumentMalwareScanStatus.SCAN_ERROR
    )
    document.malware_scanned_at = now
    write_audit_log(
        db,
        organization_id=document.organization_id,
        user_id=requested_by_id,
        action="QUARANTINE_LEGACY_DOCUMENT",
        entity_type="document",
        entity_id=document.id,
        old_values={"malware_scan_status": DocumentMalwareScanStatus.LEGACY_UNSCANNED.value},
        new_values={
            "malware_scan_status": document.malware_scan_status.value,
            "quarantined_upload_id": str(quarantined.id),
            "threat_name": threat_name,
        },
        details="Legacy evidence was blocked from download and processing after malware rescan.",
    )
    return quarantined


def rescan_legacy_document(
    db: Session,
    *,
    document: Document,
    requested_by_id: UUID | None,
) -> RescanOutcome:
    if document.malware_scan_status != DocumentMalwareScanStatus.LEGACY_UNSCANNED:
        raise EvidenceSecurityError("Document is not eligible for legacy malware rescan.")

    try:
        result = _scan_path(_storage().path_for(document.storage_key))
    except (MalwareScannerError, FileNotFoundError) as exc:
        quarantined = _logical_and_physical_quarantine(
            db,
            document=document,
            requested_by_id=requested_by_id,
            quarantine_status=QuarantineStatus.SCAN_ERROR,
            scan_error=str(exc)[:1000],
        )
        return RescanOutcome(
            status=DocumentMalwareScanStatus.SCAN_ERROR,
            quarantined_upload_id=quarantined.id,
        )

    if result.verdict == MalwareScanVerdict.INFECTED:
        quarantined = _logical_and_physical_quarantine(
            db,
            document=document,
            requested_by_id=requested_by_id,
            quarantine_status=QuarantineStatus.INFECTED,
            threat_name=result.threat_name,
        )
        return RescanOutcome(
            status=DocumentMalwareScanStatus.INFECTED_QUARANTINED,
            quarantined_upload_id=quarantined.id,
            threat_name=result.threat_name,
        )

    document.malware_scan_status = DocumentMalwareScanStatus.CLEAN
    document.malware_scanned_at = datetime.now(UTC)
    write_audit_log(
        db,
        organization_id=document.organization_id,
        user_id=requested_by_id,
        action="RESCAN_LEGACY_DOCUMENT_CLEAN",
        entity_type="document",
        entity_id=document.id,
        old_values={"malware_scan_status": DocumentMalwareScanStatus.LEGACY_UNSCANNED.value},
        new_values={
            "malware_scan_status": DocumentMalwareScanStatus.CLEAN.value,
            "malware_scanned_at": document.malware_scanned_at.isoformat(),
        },
    )
    return RescanOutcome(status=DocumentMalwareScanStatus.CLEAN)


def queue_legacy_rescans(
    db: Session,
    *,
    claim: Claim,
    current_user: User,
    limit: int,
) -> tuple[list[DocumentProcessingJob], int]:
    eligible = list(
        db.scalars(
            select(Document)
            .where(
                Document.organization_id == current_user.organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
                Document.malware_scan_status == DocumentMalwareScanStatus.LEGACY_UNSCANNED,
            )
            .order_by(Document.created_at.asc())
            .limit(limit)
        ).all()
    )
    jobs: list[DocumentProcessingJob] = []
    skipped = 0
    now = datetime.now(UTC)
    for document in eligible:
        existing = db.scalar(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.document_id == document.id,
                DocumentProcessingJob.job_type == ProcessingJobType.MALWARE_RESCAN,
                DocumentProcessingJob.status.in_(
                    [ProcessingJobStatus.PENDING, ProcessingJobStatus.RUNNING]
                ),
            )
        )
        if existing is not None:
            skipped += 1
            continue
        job = DocumentProcessingJob(
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            requested_by_id=current_user.id,
            job_type=ProcessingJobType.MALWARE_RESCAN,
            status=ProcessingJobStatus.PENDING,
            available_at=now,
            max_attempts=settings.processing_max_attempts,
        )
        db.add(job)
        jobs.append(job)

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="QUEUE_LEGACY_MALWARE_RESCAN",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "requested_limit": limit,
            "queued_count": len(jobs),
            "skipped_count": skipped,
            "document_ids": [str(job.document_id) for job in jobs],
        },
    )
    db.commit()
    for job in jobs:
        db.refresh(job)
    return jobs, skipped


def get_quarantined_upload_for_tenant(
    db: Session,
    *,
    upload_id: UUID,
    claim_id: UUID,
    organization_id: UUID,
) -> QuarantinedUpload | None:
    return db.scalar(
        select(QuarantinedUpload).where(
            QuarantinedUpload.id == upload_id,
            QuarantinedUpload.claim_id == claim_id,
            QuarantinedUpload.organization_id == organization_id,
        )
    )


def retry_quarantined_upload(
    db: Session,
    *,
    quarantined: QuarantinedUpload,
    current_user: User,
) -> Document | None:
    if quarantined.status != QuarantineStatus.SCAN_ERROR:
        raise EvidenceSecurityError("Only scanner-error quarantines can be retried.")

    now = datetime.now(UTC)
    quarantined.retry_count += 1
    quarantined.last_retried_at = now
    try:
        result = _scan_path(_storage().path_for(quarantined.quarantine_key))
    except (MalwareScannerError, FileNotFoundError) as exc:
        quarantined.scan_error = str(exc)[:1000]
        quarantined.scanned_at = now
        write_audit_log(
            db,
            organization_id=quarantined.organization_id,
            user_id=current_user.id,
            action="RETRY_QUARANTINE_SCAN_ERROR",
            entity_type="quarantined_upload",
            entity_id=quarantined.id,
            new_values={"retry_count": quarantined.retry_count, "status": quarantined.status.value},
        )
        db.commit()
        return None

    if result.verdict == MalwareScanVerdict.INFECTED:
        quarantined.status = QuarantineStatus.INFECTED
        quarantined.threat_name = result.threat_name
        quarantined.scan_error = None
        quarantined.scanned_at = now
        source = db.get(Document, quarantined.source_document_id) if quarantined.source_document_id else None
        if source is not None:
            source.malware_scan_status = DocumentMalwareScanStatus.INFECTED_QUARANTINED
            source.malware_scanned_at = now
        write_audit_log(
            db,
            organization_id=quarantined.organization_id,
            user_id=current_user.id,
            action="RETRY_QUARANTINE_INFECTED",
            entity_type="quarantined_upload",
            entity_id=quarantined.id,
            new_values={"status": quarantined.status.value, "threat_name": result.threat_name},
        )
        db.commit()
        return None

    storage = _storage()
    source = db.get(Document, quarantined.source_document_id) if quarantined.source_document_id else None
    if source is None:
        suffix = Path(quarantined.quarantine_key).suffix or Path(quarantined.original_filename).suffix.lower()
        storage_key = make_storage_key(
            organization_id=quarantined.organization_id,
            claim_id=quarantined.claim_id,
            document_id=quarantined.id,
            suffix=suffix,
        )
        if quarantined.quarantine_key != storage_key:
            try:
                storage.promote(quarantined.quarantine_key, storage_key)
            except StorageError as exc:
                raise EvidenceSecurityError("Quarantined bytes could not be promoted.") from exc
        source = Document(
            id=quarantined.id,
            organization_id=quarantined.organization_id,
            claim_id=quarantined.claim_id,
            uploaded_by_id=quarantined.uploaded_by_id,
            filename=quarantined.original_filename,
            original_filename=quarantined.original_filename,
            document_type=quarantined.document_type,
            mime_type=quarantined.mime_type,
            file_size_bytes=quarantined.file_size_bytes,
            file_hash=quarantined.file_hash,
            storage_key=storage_key,
            confidentiality_level=quarantined.confidentiality_level,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
            malware_scanned_at=now,
        )
        db.add(source)
        from app.modules.processing.service import enqueue_text_extraction

        enqueue_text_extraction(db, document=source, requested_by_id=current_user.id)
    else:
        if quarantined.quarantine_key != source.storage_key:
            try:
                storage.promote(quarantined.quarantine_key, source.storage_key)
            except StorageError as exc:
                raise EvidenceSecurityError("Quarantined bytes could not be restored.") from exc
        source.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        source.malware_scanned_at = now

    quarantined.status = QuarantineStatus.RELEASED
    quarantined.scan_error = None
    quarantined.threat_name = None
    quarantined.scanned_at = now
    quarantined.resolved_at = now
    quarantined.resolved_by_id = current_user.id
    quarantined.resolution_note = "Released after an operator-requested retry returned a clean verdict."
    write_audit_log(
        db,
        organization_id=quarantined.organization_id,
        user_id=current_user.id,
        action="RELEASE_QUARANTINE_AFTER_CLEAN_RETRY",
        entity_type="quarantined_upload",
        entity_id=quarantined.id,
        new_values={
            "status": quarantined.status.value,
            "document_id": str(source.id),
            "retry_count": quarantined.retry_count,
        },
        details="Release required an explicit operator retry and an authoritative clean verdict.",
    )
    db.commit()
    db.refresh(source)
    return source


def purge_quarantined_upload(
    db: Session,
    *,
    quarantined: QuarantinedUpload,
    current_user: User,
    reason: str,
) -> None:
    if quarantined.status not in {QuarantineStatus.INFECTED, QuarantineStatus.SCAN_ERROR}:
        raise EvidenceSecurityError("Only unresolved quarantines can be purged.")
    old_status = quarantined.status
    _storage().delete_physical(quarantined.quarantine_key)
    now = datetime.now(UTC)
    quarantined.status = QuarantineStatus.PURGED
    quarantined.resolved_at = now
    quarantined.resolved_by_id = current_user.id
    quarantined.resolution_note = reason
    write_audit_log(
        db,
        organization_id=quarantined.organization_id,
        user_id=current_user.id,
        action="PURGE_QUARANTINED_UPLOAD",
        entity_type="quarantined_upload",
        entity_id=quarantined.id,
        old_values={"status": old_status.value, "file_hash": quarantined.file_hash},
        new_values={"status": QuarantineStatus.PURGED.value},
        details=reason,
    )
    db.commit()
