from datetime import UTC, date, datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.modules.claims.models import Claim
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.organizations.models import Organization
from app.modules.processing.lease_recovery import (
    ProcessingLeaseLost,
    activate_processing_lease_guard,
    clear_processing_lease_guard,
    recover_stale_processing_jobs,
)
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.processing.service import claim_next_job
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL lease-fencing regression requires the PostgreSQL CI job",
)
def test_recovered_processing_lease_fences_late_old_worker_flush() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, class_=Session)
    unique = uuid4().hex[:12]

    with SessionLocal() as db:
        organization = Organization(name=f"Lease Fence {unique}", slug=f"lease-fence-{unique}")
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email=f"lease-{unique}@example.test",
            full_name="Lease Fence Handler",
            password_hash="test-only-not-authenticated",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        vessel = Vessel(
            organization_id=organization.id,
            name=f"MT LEASE {unique}",
            imo_number=None,
        )
        db.add_all([user, vessel])
        db.flush()
        claim = Claim(
            organization_id=organization.id,
            vessel_id=vessel.id,
            handler_id=user.id,
            claim_reference=f"LEASE-{unique}",
            incident_date=date(2026, 9, 1),
            notification_date=date(2026, 9, 2),
            incident_description="PostgreSQL stale processing lease fencing regression.",
            currency="USD",
        )
        db.add(claim)
        db.flush()
        document = Document(
            organization_id=organization.id,
            claim_id=claim.id,
            uploaded_by_id=user.id,
            filename="authoritative-name.pdf",
            original_filename="authoritative-name.pdf",
            document_type="survey_report",
            mime_type="application/pdf",
            file_size_bytes=256,
            file_hash=("cd" * 32),
            storage_key=f"tests/{claim.id}/authoritative-name.pdf",
            processing_status=DocumentProcessingStatus.PROCESSING,
        )
        db.add(document)
        db.flush()
        job = DocumentProcessingJob(
            organization_id=organization.id,
            claim_id=claim.id,
            document_id=document.id,
            job_type=ProcessingJobType.EXTRACT_TEXT,
            status=ProcessingJobStatus.RUNNING,
            attempt_count=1,
            max_attempts=3,
            available_at=datetime.now(UTC) - timedelta(hours=2),
            locked_at=datetime.now(UTC) - timedelta(hours=2),
            locked_by="old-worker",
            requested_by_id=user.id,
        )
        db.add(job)
        db.commit()
        job_id = job.id
        document_id = document.id

    old_worker = SessionLocal()
    try:
        old_job = old_worker.get(DocumentProcessingJob, job_id)
        old_document = old_worker.get(Document, document_id)
        assert old_job is not None and old_document is not None
        activate_processing_lease_guard(old_worker, job=old_job)

        with SessionLocal() as recovery:
            assert recover_stale_processing_jobs(recovery, document_id=document_id) == 1
            recovered = recovery.get(DocumentProcessingJob, job_id)
            assert recovered is not None
            assert recovered.status == ProcessingJobStatus.PENDING
            recovered.available_at = datetime.now(UTC) - timedelta(seconds=1)
            recovery.commit()

        with SessionLocal() as successor:
            successor_job = claim_next_job(successor, worker_id="successor-worker")
            assert successor_job is not None
            assert successor_job.id == job_id
            assert successor_job.status == ProcessingJobStatus.RUNNING
            assert successor_job.attempt_count == 2
            assert successor_job.locked_by == "successor-worker"

        old_document.filename = "stale-worker-must-not-commit.pdf"
        with pytest.raises(ProcessingLeaseLost):
            old_worker.flush()
        old_worker.rollback()
    finally:
        clear_processing_lease_guard(old_worker)
        old_worker.close()

    with SessionLocal() as verify:
        job = verify.get(DocumentProcessingJob, job_id)
        document = verify.get(Document, document_id)
        assert job is not None and document is not None
        assert job.status == ProcessingJobStatus.RUNNING
        assert job.attempt_count == 2
        assert job.locked_by == "successor-worker"
        assert document.filename == "authoritative-name.pdf"

    engine.dispose()
