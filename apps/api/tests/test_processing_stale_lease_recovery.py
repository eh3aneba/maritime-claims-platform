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
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _seed_running_job(*, attempt_count: int, max_attempts: int) -> tuple[UUID, UUID, UUID]:
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
        return claim_id, document.id, job.id


def test_stale_running_processing_job_returns_to_pending_with_backoff() -> None:
    _claim_id, document_id, job_id = _seed_running_job(attempt_count=1, max_attempts=3)

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
        assert job.available_at is not None
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
    _claim_id, document_id, job_id = _seed_running_job(attempt_count=3, max_attempts=3)

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


def test_retry_endpoint_recovers_expired_running_extraction_instead_of_echoing_it() -> None:
    claim_id, document_id, job_id = _seed_running_job(attempt_count=1, max_attempts=3)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    response = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry"
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["id"] == str(job_id)
    assert payload["status"] == ProcessingJobStatus.PENDING.value

    with TestingSessionLocal() as db:
        job = db.get(DocumentProcessingJob, job_id)
        assert job is not None
        assert job.status == ProcessingJobStatus.PENDING
        assert job.locked_by is None
        assert job.locked_at is None
        assert job.attempt_count == 1



def test_processing_summary_marks_stale_running_job_as_recoverable() -> None:
    claim_id, document_id, _job_id = _seed_running_job(attempt_count=1, max_attempts=3)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    response = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["operator_status"] == "running"
    assert payload["can_retry"] is True
    assert payload["retry_recommended"] is True
    assert payload["job"]["attempt_count"] == 1
    assert payload["job"]["max_attempts"] == 3
    assert "locked_by" not in payload["job"]
    assert "locked_at" not in payload["job"]


def test_processing_summary_changes_to_queued_after_stale_retry_recovery() -> None:
    claim_id, document_id, job_id = _seed_running_job(attempt_count=1, max_attempts=3)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry"
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["id"] == str(job_id)
    assert retry.json()["status"] == "pending"

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing"
    )
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["operator_status"] == "queued"
    assert payload["can_retry"] is False
    assert payload["retry_recommended"] is False


def test_processing_summary_marks_terminal_failure_retryable() -> None:
    claim_id, document_id, _job_id = _seed_running_job(attempt_count=3, max_attempts=3)

    with TestingSessionLocal() as db:
        assert recover_stale_processing_jobs(db, document_id=document_id) == 1

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing"
    )
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["operator_status"] == "failed"
    assert payload["can_retry"] is True
    assert payload["retry_recommended"] is True
    assert payload["job"]["attempt_count"] == 3
    assert payload["job"]["max_attempts"] == 3
