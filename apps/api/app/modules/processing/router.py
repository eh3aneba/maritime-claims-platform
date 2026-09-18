from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.security import get_document_for_tenant
from app.modules.processing.lease_recovery import (\n    is_processing_job_stale,\n    recover_stale_processing_jobs,\n)
from app.modules.processing.models import ProcessingJobStatus, ProcessingJobType
from app.modules.processing.schemas import (
    DocumentProcessingSummary,
    OperatorProcessingJobResponse,
    ProcessingJobResponse,
)
from app.modules.processing.service import enqueue_text_extraction, get_processing_summary

router = APIRouter(prefix="/claims/{claim_id}/documents/{document_id}/processing", tags=["document-processing"])
def _operator_state(document, job):
    if job is None:
        if document.processing_status.value == "processed":
            return "completed", False, False
        if document.processing_status.value == "failed":
            return "failed", True, True
        return "uploaded", True, True

    if job.status == ProcessingJobStatus.PENDING:
        return "queued", False, False
    if job.status == ProcessingJobStatus.RUNNING:
        if is_processing_job_stale(job):
            return "running", True, True
        return "running", False, False
    if job.status == ProcessingJobStatus.COMPLETED:
        return "completed", False, False
    return "failed", True, True


@router.get("", response_model=DocumentProcessingSummary)
def processing_summary(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentProcessingSummary:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(
        db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    job, extraction = get_processing_summary(
        db, document_id=document.id, organization_id=current_user.organization_id
    )
    operator_status, can_retry, retry_recommended = _operator_state(document, job)
    return DocumentProcessingSummary(
        job=OperatorProcessingJobResponse.model_validate(job) if job else None,
        text_extraction=extraction,
        operator_status=operator_status,
        can_retry=can_retry,
        retry_recommended=retry_recommended,
    )


@router.post("/retry", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_processing(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ProcessingJobResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(
        db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Retry is also an operator recovery point. A genuinely active lease remains
    # untouched, while an expired RUNNING extraction is returned to the bounded
    # attempt queue (or terminally failed when its budget is exhausted).
    recover_stale_processing_jobs(
        db,
        document_id=document.id,
        job_type=ProcessingJobType.EXTRACT_TEXT,
        limit=1,
    )
    job = enqueue_text_extraction(db, document=document, requested_by_id=current_user.id)
    db.commit()
    db.refresh(job)
    return ProcessingJobResponse.model_validate(job)
