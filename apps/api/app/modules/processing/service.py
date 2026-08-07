from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.documents.storage import LocalDocumentStorage
from app.modules.processing.extractors import EXTRACTOR_VERSION, extract_document_text
from app.modules.processing.models import (
    DocumentProcessingJob,
    DocumentTextExtraction,
    DocumentTextSegment,
    ProcessingJobStatus,
    ProcessingJobType,
)

settings = get_settings()


def _storage() -> LocalDocumentStorage:
    if settings.storage_backend != "local":
        raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
    return LocalDocumentStorage(settings.local_storage_path, max_upload_bytes=settings.max_upload_bytes)


def enqueue_processing_job(
    db: Session,
    *,
    document: Document,
    requested_by_id: UUID | None,
    job_type: ProcessingJobType,
) -> DocumentProcessingJob:
    existing = db.scalar(
        select(DocumentProcessingJob).where(
            DocumentProcessingJob.document_id == document.id,
            DocumentProcessingJob.job_type == job_type,
            DocumentProcessingJob.status.in_([ProcessingJobStatus.PENDING, ProcessingJobStatus.RUNNING]),
        )
    )
    if existing is not None:
        return existing
    job = DocumentProcessingJob(
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        requested_by_id=requested_by_id,
        job_type=job_type,
        status=ProcessingJobStatus.PENDING,
        available_at=datetime.now(UTC),
        max_attempts=settings.processing_max_attempts,
    )
    db.add(job)
    return job


def enqueue_text_extraction(
    db: Session,
    *,
    document: Document,
    requested_by_id: UUID | None,
) -> DocumentProcessingJob:
    return enqueue_processing_job(
        db, document=document, requested_by_id=requested_by_id, job_type=ProcessingJobType.EXTRACT_TEXT
    )


def claim_next_job(db: Session, *, worker_id: str) -> DocumentProcessingJob | None:
    now = datetime.now(UTC)
    stmt = (
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.status == ProcessingJobStatus.PENDING,
            DocumentProcessingJob.available_at <= now,
            DocumentProcessingJob.attempt_count < DocumentProcessingJob.max_attempts,
        )
        .order_by(DocumentProcessingJob.created_at.asc())
        .limit(1)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = ProcessingJobStatus.RUNNING
    job.locked_at = now
    job.locked_by = worker_id[:120]
    job.started_at = job.started_at or now
    job.attempt_count += 1
    db.commit()
    db.refresh(job)
    return job


def process_job(db: Session, *, job: DocumentProcessingJob) -> None:
    if job.job_type == ProcessingJobType.EXTRACT_TEXT:
        _process_text_job(db, job=job)
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_CE_REPORT:
        _process_ce_ai_job(db, job=job)
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_ENGINE_LOG:
        _process_engine_log_ai_job(db, job=job)
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_RUNNING_HOURS:
        _process_named_ai_job(db, job=job, runner_name="run_running_hours_intelligence")
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_PMS_HISTORY:
        _process_named_ai_job(db, job=job, runner_name="run_pms_history_intelligence")
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_WORKSHOP_REPORT:
        _process_named_ai_job(db, job=job, runner_name="run_workshop_report_intelligence")
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_QUOTATION:
        _process_named_ai_job(db, job=job, runner_name="run_quotation_intelligence")
        return
    if job.job_type == ProcessingJobType.AI_EXTRACT_INVOICE:
        _process_named_ai_job(db, job=job, runner_name="run_invoice_intelligence")
        return
    _fail_job(db, job=job, document=db.get(Document, job.document_id), error=f"Unsupported job type: {job.job_type}")


def _process_text_job(db: Session, *, job: DocumentProcessingJob) -> None:
    document = db.get(Document, job.document_id)
    if document is None or document.deleted_at is not None:
        _fail_job(db, job=job, document=document, error="Document is unavailable or deleted.")
        return
    document.processing_status = DocumentProcessingStatus.PROCESSING
    db.commit()
    try:
        path = _storage().path_for(document.storage_key)
        result = extract_document_text(path)
        extraction = db.scalar(select(DocumentTextExtraction).where(DocumentTextExtraction.document_id == document.id))
        if extraction is None:
            extraction = DocumentTextExtraction(
                organization_id=document.organization_id,
                document_id=document.id,
                extraction_method=result.method,
                extractor_version=EXTRACTOR_VERSION,
            )
            db.add(extraction)
            db.flush()
        else:
            db.execute(delete(DocumentTextSegment).where(DocumentTextSegment.extraction_id == extraction.id))
            extraction.extraction_method = result.method
            extraction.extractor_version = EXTRACTOR_VERSION

        total_chars = 0
        for index, segment in enumerate(result.segments):
            text = segment.text.strip()
            total_chars += len(text)
            db.add(
                DocumentTextSegment(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    extraction_id=extraction.id,
                    segment_index=index,
                    locator_type=segment.locator_type,
                    locator_value=segment.locator_value,
                    text=text,
                    char_count=len(text),
                )
            )
        extraction.char_count = total_chars
        extraction.segment_count = len(result.segments)
        extraction.requires_ocr = result.requires_ocr
        extraction.text_hash = result.text_hash
        extraction.warnings = result.warnings

        document.processing_status = DocumentProcessingStatus.PROCESSED
        job.status = ProcessingJobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.locked_at = None
        job.locked_by = None
        job.last_error = None
        job.result = {
            "method": result.method,
            "char_count": total_chars,
            "segment_count": len(result.segments),
            "requires_ocr": result.requires_ocr,
            "warnings": result.warnings,
        }
        write_audit_log(
            db,
            organization_id=document.organization_id,
            user_id=job.requested_by_id,
            action="EXTRACT_DOCUMENT_TEXT",
            entity_type="document",
            entity_id=document.id,
            new_values=job.result,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        refreshed_document = db.get(Document, job.document_id)
        if refreshed_job is not None:
            _fail_job(db, job=refreshed_job, document=refreshed_document, error=str(exc))


def _process_ce_ai_job(db: Session, *, job: DocumentProcessingJob) -> None:
    document = db.get(Document, job.document_id)
    if document is None or document.deleted_at is not None:
        _fail_job(db, job=job, document=document, error="Document is unavailable or deleted.")
        return
    try:
        from app.modules.intelligence.service import run_ce_report_intelligence

        run = run_ce_report_intelligence(
            db, document=document, requested_by_id=job.requested_by_id
        )
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        if refreshed_job is None:
            return
        refreshed_job.status = ProcessingJobStatus.COMPLETED
        refreshed_job.completed_at = datetime.now(UTC)
        refreshed_job.locked_at = None
        refreshed_job.locked_by = None
        refreshed_job.last_error = None
        refreshed_job.result = {
            "ai_run_id": str(run.id),
            "classification": run.document_type_candidate,
            "classification_confidence": float(run.classification_confidence or 0),
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        refreshed_document = db.get(Document, job.document_id)
        if refreshed_job is not None:
            _fail_job(db, job=refreshed_job, document=refreshed_document, error=str(exc))


def _process_engine_log_ai_job(db: Session, *, job: DocumentProcessingJob) -> None:
    document = db.get(Document, job.document_id)
    if document is None or document.deleted_at is not None:
        _fail_job(db, job=job, document=document, error="Document is unavailable or deleted.")
        return
    try:
        from app.modules.intelligence.service import run_engine_log_intelligence

        run = run_engine_log_intelligence(
            db, document=document, requested_by_id=job.requested_by_id
        )
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        if refreshed_job is None:
            return
        refreshed_job.status = ProcessingJobStatus.COMPLETED
        refreshed_job.completed_at = datetime.now(UTC)
        refreshed_job.locked_at = None
        refreshed_job.locked_by = None
        refreshed_job.last_error = None
        refreshed_job.result = {
            "ai_run_id": str(run.id),
            "classification": run.document_type_candidate,
            "classification_confidence": float(run.classification_confidence or 0),
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        refreshed_document = db.get(Document, job.document_id)
        if refreshed_job is not None:
            _fail_job(db, job=refreshed_job, document=refreshed_document, error=str(exc))



def _process_named_ai_job(db: Session, *, job: DocumentProcessingJob, runner_name: str) -> None:
    document = db.get(Document, job.document_id)
    if document is None or document.deleted_at is not None:
        _fail_job(db, job=job, document=document, error="Document is unavailable or deleted.")
        return
    try:
        from app.modules import intelligence as intelligence_module  # noqa: F401
        from app.modules.intelligence import service as intelligence_service

        runner = getattr(intelligence_service, runner_name)
        run = runner(db, document=document, requested_by_id=job.requested_by_id)
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        if refreshed_job is None:
            return
        refreshed_job.status = ProcessingJobStatus.COMPLETED
        refreshed_job.completed_at = datetime.now(UTC)
        refreshed_job.locked_at = None
        refreshed_job.locked_by = None
        refreshed_job.last_error = None
        refreshed_job.result = {
            "ai_run_id": str(run.id),
            "classification": run.document_type_candidate,
            "classification_confidence": float(run.classification_confidence or 0),
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        refreshed_job = db.get(DocumentProcessingJob, job.id)
        refreshed_document = db.get(Document, job.document_id)
        if refreshed_job is not None:
            _fail_job(db, job=refreshed_job, document=refreshed_document, error=str(exc))


def _fail_job(db: Session, *, job: DocumentProcessingJob, document: Document | None, error: str) -> None:
    final_failure = job.attempt_count >= job.max_attempts
    job.status = ProcessingJobStatus.FAILED if final_failure else ProcessingJobStatus.PENDING
    job.last_error = error[:4000]
    job.locked_at = None
    job.locked_by = None
    if final_failure:
        job.completed_at = datetime.now(UTC)
        if document is not None and job.job_type == ProcessingJobType.EXTRACT_TEXT:
            document.processing_status = DocumentProcessingStatus.FAILED
    elif document is not None and job.job_type == ProcessingJobType.EXTRACT_TEXT:
        document.processing_status = DocumentProcessingStatus.UPLOADED
    db.commit()


def get_processing_summary(db: Session, *, document_id: UUID, organization_id: UUID) -> tuple[DocumentProcessingJob | None, DocumentTextExtraction | None]:
    job = db.scalar(
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.document_id == document_id,
            DocumentProcessingJob.organization_id == organization_id,
            DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT,
        )
        .order_by(DocumentProcessingJob.created_at.desc())
        .limit(1)
    )
    extraction = db.scalar(
        select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == document_id,
            DocumentTextExtraction.organization_id == organization_id,
        )
    )
    return job, extraction
