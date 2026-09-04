from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.intake.models import ClaimIntakeDraft, ClaimIntakeProcessingJob, ClaimIntakeStatus
from app.modules.intake.service import process_intake_job as _legacy_process_intake_job
from app.modules.processing.models import ProcessingJobStatus
from app.modules.users.models import User

_TERMINAL_FAILURE_MARKERS = (
    "No reviewable text was extracted from the intake source.",
)


def _is_terminal_failure(error: str | None) -> bool:
    message = error or ""
    return any(marker in message for marker in _TERMINAL_FAILURE_MARKERS)


def process_intake_job(db: Session, *, job: ClaimIntakeProcessingJob) -> None:
    """Run intake processing while preserving retry semantics for transient failures.

    The original intake processor records all extractor/runtime failures durably. This
    wrapper promotes non-terminal failures back to PENDING until max_attempts is
    exhausted, matching the general document-processing queue behavior.
    """
    _legacy_process_intake_job(db, job=job)
    db.expire_all()
    refreshed_job = db.get(ClaimIntakeProcessingJob, job.id)
    if refreshed_job is None or refreshed_job.status != ProcessingJobStatus.FAILED:
        return
    if _is_terminal_failure(refreshed_job.last_error):
        return
    if refreshed_job.attempt_count >= refreshed_job.max_attempts:
        return

    draft = db.get(ClaimIntakeDraft, refreshed_job.intake_draft_id)
    if draft is None or draft.status != ClaimIntakeStatus.FAILED:
        return

    delay_seconds = min(30, 2 ** max(refreshed_job.attempt_count - 1, 0))
    refreshed_job.status = ProcessingJobStatus.PENDING
    refreshed_job.available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    refreshed_job.completed_at = None
    refreshed_job.locked_at = None
    refreshed_job.locked_by = None
    draft.status = ClaimIntakeStatus.PROCESSING
    draft.extraction_warnings = [
        f"Transient processing failure; automatic retry {refreshed_job.attempt_count + 1} "
        f"of {refreshed_job.max_attempts} is scheduled."
    ]
    write_audit_log(
        db,
        organization_id=draft.organization_id,
        user_id=refreshed_job.requested_by_id,
        action="REQUEUE_CLAIM_INTAKE_PROCESSING",
        entity_type="claim_intake_draft",
        entity_id=draft.id,
        new_values={
            "attempt_count": refreshed_job.attempt_count,
            "max_attempts": refreshed_job.max_attempts,
            "available_at": refreshed_job.available_at.isoformat(),
        },
        details=(refreshed_job.last_error or "Transient intake processing failure")[:1000],
    )
    db.commit()


def retry_failed_intake_draft(
    db: Session,
    *,
    draft_id: UUID,
    organization_id: UUID,
    current_user: User,
) -> ClaimIntakeDraft:
    draft = db.scalar(
        select(ClaimIntakeDraft).where(
            ClaimIntakeDraft.id == draft_id,
            ClaimIntakeDraft.organization_id == organization_id,
        )
    )
    if draft is None:
        raise LookupError("Claim intake draft not found")
    if draft.status != ClaimIntakeStatus.FAILED:
        raise ValueError(f"Draft cannot be retried from status {draft.status.value}.")

    job = db.scalar(
        select(ClaimIntakeProcessingJob).where(
            ClaimIntakeProcessingJob.intake_draft_id == draft.id,
            ClaimIntakeProcessingJob.organization_id == organization_id,
        )
    )
    if job is None:
        raise RuntimeError("Claim intake processing job is missing.")

    job.status = ProcessingJobStatus.PENDING
    job.attempt_count = 0
    job.available_at = datetime.now(UTC)
    job.locked_at = None
    job.locked_by = None
    job.started_at = None
    job.completed_at = None
    job.last_error = None
    job.result = None
    draft.status = ClaimIntakeStatus.PROCESSING
    draft.extraction_warnings = ["Manual reprocess requested by a claims user."]

    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=current_user.id,
        action="RETRY_CLAIM_INTAKE_PROCESSING",
        entity_type="claim_intake_draft",
        entity_id=draft.id,
        new_values={"status": draft.status.value, "attempt_count": 0},
        details="Explicit operator retry after a terminal intake processing failure.",
    )
    db.commit()
    db.refresh(draft)
    return draft
