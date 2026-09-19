from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)

settings = get_settings()

_LEASE_INFO_KEY = "mcri_processing_lease_fence"
_TERMINAL_FLUSH_KEY = "mcri_processing_lease_terminal_flush"
_TERMINAL_COMMITTED_KEY = "mcri_processing_lease_terminal_committed"
_TERMINAL_STATUSES = {ProcessingJobStatus.COMPLETED, ProcessingJobStatus.FAILED}


class ProcessingLeaseLost(RuntimeError):
    """Raised before a stale worker can flush writes after its lease was reassigned."""


@dataclass(frozen=True)
class ProcessingLeaseFingerprint:
    job_id: UUID
    attempt_count: int
    locked_by: str
    locked_at: datetime


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_timestamp(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return _aware(left) == _aware(right)


def capture_processing_lease(job: DocumentProcessingJob) -> ProcessingLeaseFingerprint:
    if (
        job.status != ProcessingJobStatus.RUNNING
        or job.locked_by is None
        or job.locked_at is None
        or job.attempt_count <= 0
    ):
        raise ProcessingLeaseLost("Document processing job does not hold a valid running lease")
    return ProcessingLeaseFingerprint(
        job_id=job.id,
        attempt_count=job.attempt_count,
        locked_by=job.locked_by,
        locked_at=job.locked_at,
    )


def activate_processing_lease_guard(db: Session, *, job: DocumentProcessingJob) -> ProcessingLeaseFingerprint:
    token = capture_processing_lease(job)
    db.info[_LEASE_INFO_KEY] = token
    db.info[_TERMINAL_FLUSH_KEY] = False
    db.info[_TERMINAL_COMMITTED_KEY] = False
    return token


def clear_processing_lease_guard(db: Session) -> None:
    db.info.pop(_LEASE_INFO_KEY, None)
    db.info.pop(_TERMINAL_FLUSH_KEY, None)
    db.info.pop(_TERMINAL_COMMITTED_KEY, None)


def _database_lease(db: Session, job_id: UUID):
    with db.no_autoflush:
        return db.execute(
            select(
                DocumentProcessingJob.status,
                DocumentProcessingJob.attempt_count,
                DocumentProcessingJob.locked_by,
                DocumentProcessingJob.locked_at,
            ).where(DocumentProcessingJob.id == job_id)
        ).one_or_none()


@event.listens_for(Session, "before_flush")
def _fence_processing_flush(db: Session, _flush_context, _instances) -> None:
    token = db.info.get(_LEASE_INFO_KEY)
    if token is None or db.info.get(_TERMINAL_COMMITTED_KEY):
        return

    row = _database_lease(db, token.job_id)
    if row is None:
        raise ProcessingLeaseLost("Document processing lease record disappeared")
    status, attempt_count, locked_by, locked_at = row
    if (
        status != ProcessingJobStatus.RUNNING
        or attempt_count != token.attempt_count
        or locked_by != token.locked_by
        or not _same_timestamp(locked_at, token.locked_at)
    ):
        raise ProcessingLeaseLost("Document processing lease was recovered or reassigned")

    for obj in db.dirty:
        if (
            isinstance(obj, DocumentProcessingJob)
            and obj.id == token.job_id
            and obj.status in _TERMINAL_STATUSES
        ):
            db.info[_TERMINAL_FLUSH_KEY] = True
            break


@event.listens_for(Session, "after_commit")
def _mark_terminal_processing_commit(db: Session) -> None:
    if db.info.get(_LEASE_INFO_KEY) is not None and db.info.get(_TERMINAL_FLUSH_KEY):
        db.info[_TERMINAL_COMMITTED_KEY] = True


def process_job_with_lease(db: Session, *, job: DocumentProcessingJob, processor) -> bool:
    """Run one claimed job while fencing every flush to its exact lease attempt.

    The wrapped processing code contains nested commits, including AI-run commits.
    The Session guard therefore protects every flush rather than only the final job
    status update. If recovery/reassignment occurs while expensive work is running,
    late writes are rolled back and the successor lease remains authoritative.
    """

    activate_processing_lease_guard(db, job=job)
    try:
        processor(db, job=job)
        return True
    except ProcessingLeaseLost:
        db.rollback()
        return False
    finally:
        clear_processing_lease_guard(db)


def _retry_delay_seconds(attempt_count: int) -> int:
    # Keep recovery bounded and quick while avoiding an immediate crash loop.
    return min(300, 15 * (2 ** max(0, attempt_count - 1)))


def processing_stale_cutoff(*, now: datetime | None = None) -> datetime:
    reference = now or datetime.now(UTC)
    return reference - timedelta(seconds=settings.processing_stale_after_seconds)


def is_processing_job_stale(
    job: DocumentProcessingJob,
    *,
    now: datetime | None = None,
) -> bool:
    return (
        job.status == ProcessingJobStatus.RUNNING
        and job.locked_at is not None
        and _aware(job.locked_at) < processing_stale_cutoff(now=now)
    )


def recover_stale_processing_jobs(
    db: Session,
    *,
    document_id: UUID | None = None,
    job_type: ProcessingJobType | None = None,
    limit: int = 50,
) -> int:
    """Recover expired RUNNING document jobs using the existing attempt budget.

    Recovery changes the durable lease fields. Any still-alive old worker protected
    by ``process_job_with_lease`` will then fail its next flush before stale results
    can become authoritative.
    """

    now = datetime.now(UTC)
    cutoff = processing_stale_cutoff(now=now)
    conditions = [
        DocumentProcessingJob.status == ProcessingJobStatus.RUNNING,
        DocumentProcessingJob.locked_at.is_not(None),
        DocumentProcessingJob.locked_at < cutoff,
    ]
    if document_id is not None:
        conditions.append(DocumentProcessingJob.document_id == document_id)
    if job_type is not None:
        conditions.append(DocumentProcessingJob.job_type == job_type)

    stmt = (
        select(DocumentProcessingJob)
        .where(*conditions)
        .order_by(DocumentProcessingJob.locked_at.asc())
        .limit(max(1, min(limit, 200)))
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    jobs = list(db.scalars(stmt).all())
    for job in jobs:
        prior_worker = job.locked_by
        prior_locked_at = job.locked_at
        exhausted = job.attempt_count >= job.max_attempts
        document = db.get(Document, job.document_id)

        job.locked_at = None
        job.locked_by = None
        job.last_error = (
            "Document processing worker lease expired before completion "
            f"(attempt {job.attempt_count}/{job.max_attempts})."
        )

        if exhausted:
            job.status = ProcessingJobStatus.FAILED
            job.completed_at = now
            if (
                document is not None
                and job.job_type == ProcessingJobType.EXTRACT_TEXT
                and document.processing_status == DocumentProcessingStatus.PROCESSING
            ):
                document.processing_status = DocumentProcessingStatus.FAILED
        else:
            job.status = ProcessingJobStatus.PENDING
            job.completed_at = None
            job.available_at = now + timedelta(seconds=_retry_delay_seconds(job.attempt_count))
            if (
                document is not None
                and job.job_type == ProcessingJobType.EXTRACT_TEXT
                and document.processing_status == DocumentProcessingStatus.PROCESSING
            ):
                document.processing_status = DocumentProcessingStatus.UPLOADED

        write_audit_log(
            db,
            organization_id=job.organization_id,
            user_id=job.requested_by_id,
            action=(
                "FAIL_STALE_DOCUMENT_PROCESSING_JOB"
                if exhausted
                else "RECOVER_STALE_DOCUMENT_PROCESSING_JOB"
            ),
            entity_type="document_processing_jobs",
            entity_id=job.id,
            new_values={
                "status": job.status.value,
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
                "prior_worker": prior_worker,
                "prior_locked_at": _aware(prior_locked_at).isoformat() if prior_locked_at else None,
                "available_at": _aware(job.available_at).isoformat() if job.available_at else None,
            },
            details=(
                "Expired processing lease recovered using the existing attempt budget. "
                "Late writes from the prior lease are fenced by the exact attempt/owner/timestamp fingerprint."
            ),
        )

    if jobs:
        db.commit()
    return len(jobs)
