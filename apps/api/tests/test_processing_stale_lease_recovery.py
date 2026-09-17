from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.processing.lease_recovery import recover_stale_processing_jobs
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _seed_running_job(*, attempt_count: int, max_attempts: int) -> tuple[UUID, UUID]:
    seeded = create_orion_claim()
    claim_id = UUID(seeded["claim"]["id"])
    organization_id = seeded["seed"]["alpha"].id
    handler_id = seeded["seed"]["handler"].id

    with TestingSessionLocal() as db:
        document = Document(
            organization_id=organization_id,
            claim_id=claim_id,
            uploaded_by_id=handler_id,
            filename="stale-worker.pdf",
            original_filename="stale-worker.pdf",
            document_type="survey_report",
            mime_type="application/pdf",
            file_size_bytes=128,
            file_hash=("ab" * 32),
            storage_key=f"tests/{claim_id}/stale-worker.pdf",
            processing_status=DocumentProcessingStatus.PROCESSING,
        )
        db.add(document)
        db.flush()
        job = DocumentProcessingJob(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document.id,
            job_type=ProcessingJobType.EXTRACT_TEXT,
            status=ProcessingJobStatus.RUNNING,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            available_at=datetime.now(UTC) - timedelta(hours=2),
            locked_at=datetime.now(UTC) - timedelta(hours=2),
            locked_by="dead-worker",
            requested_by_id=handler_id,
        )
        db.add(job)
        db.commit()
        return document.id, job.id


def test_stale_running_processing_job_returns_to_pending_with_backoff() -> None:
    document_id, job_id = _seed_running_job(attempt_count=1, max_attempts=3)

    with TestingSessionLocal() as db:
        recovered = recover_stale_processing_jobs(db, document_id=document_id)
        assert recovered == 1

    with TestingSessionLocal() as db:
        job = db.get(DocumentProcessingJob, job_id)
        document = db.get(Document, document_id)
        assert job is not None
        assert document is not None
        assert job.status == ProcessingJobStatus.PENDING
        assert job.attempt_count == 1
        assert job.locked_at is None
        assert job.locked_by is None
        assert job.completed_at is None
        assert job.available_at > datetime.now(UTC)
        assert "lease expired" in (job.last_error or "").lower()
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == job_id,
                AuditLog.action == "RECOVER_STALE_DOCUMENT_PROCESSING_JOB",
            )
        )
        assert audit is not None


def test_stale_final_attempt_becomes_failed_and_actionable() -> None:
    document_id, job_id = _seed_running_job(attempt_count=3, max_attempts=3)

    with TestingSessionLocal() as db:
        recovered = recover_stale_processing_jobs(db, document_id=document_id)
        assert recovered == 1

    with TestingSessionLocal() as db:
        job = db.get(DocumentProcessingJob, job_id)
        document = db.get(Document, document_id)
        assert job is not None
        assert document is not None
        assert job.status == ProcessingJobStatus.FAILED
        assert job.attempt_count == 3
        assert job.locked_at is None
        assert job.locked_by is None
        assert job.completed_at is not None
        assert document.processing_status == DocumentProcessingStatus.FAILED
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == job_id,
                AuditLog.action == "FAIL_STALE_DOCUMENT_PROCESSING_JOB",
            )
        )
        assert audit is not None
