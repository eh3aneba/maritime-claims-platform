from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.documents.security import get_document_for_tenant
from app.modules.processing.lease_recovery import (
    is_processing_job_stale,
    recover_stale_processing_jobs,
)
from app.modules.processing.models import (
    DocumentTextExtraction,
    DocumentTextSegment,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.processing.schemas import (
    DocumentProcessingSummary,
    OperatorProcessingJobResponse,
    ProcessingJobResponse,
    SourceExtractionSegment,
    SourceExtractionSegmentsResponse,
    TextExtractionSummary,
)
from app.modules.processing.service import (
    ExternalEvidenceProcessingAuthorizationRequired,
    enqueue_text_extraction,
    external_evidence_processing_release_status,
    external_evidence_requires_processing_release,
    get_processing_summary,
)

router = APIRouter(prefix="/claims/{claim_id}/documents/{document_id}/processing", tags=["document-processing"])


def _operator_state(document, job, *, processing_release_required: bool = False):
    if job is None:
        if document.processing_status.value == "processed":
            return "completed", False, False
        if document.processing_status.value == "failed":
            return "failed", True, True
        if processing_release_required:
            return "uploaded", False, False
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
    processing_release_status = external_evidence_processing_release_status(
        db,
        document=document,
    )
    processing_release_required = processing_release_status in {"required", "revoked"}
    operator_status, can_retry, retry_recommended = _operator_state(
        document,
        job,
        processing_release_required=processing_release_required,
    )
    return DocumentProcessingSummary(
        job=OperatorProcessingJobResponse.model_validate(job) if job else None,
        text_extraction=extraction,
        operator_status=operator_status,
        can_retry=can_retry,
        retry_recommended=retry_recommended,
        processing_release_required=processing_release_required,
        processing_release_status=processing_release_status,
    )


# Only an authenticated claimant-side reviewer can inspect the persisted
# machine extraction. No customer transcript enters CI logs or search audit.
# A bounded preview avoids huge API responses and cannot be treated as
# a complete transcription when text_truncated=True.
_SOURCE_SEGMENT_TEXT_LIMIT = 12_000


@router.get("/source-segments", response_model=SourceExtractionSegmentsResponse)
def read_unverified_source_segments(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    limit: Annotated[int, Query(ge=1, le=5)] = 5,
) -> SourceExtractionSegmentsResponse:
    response.headers["Cache-Control"] = "no-store"
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    document = get_document_for_tenant(
        db, document_id=document_id, claim_id=claim.id,
        organization_id=current_user.organization_id,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if (
        document.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or document.processing_status != DocumentProcessingStatus.PROCESSED
        or external_evidence_requires_processing_release(db, document=document)
    ):
        raise HTTPException(
            status_code=409,
            detail="Clean, processed, authorized evidence is required for source comparison",
        )

    extraction = db.scalar(
        select(DocumentTextExtraction).where(
            DocumentTextExtraction.organization_id == current_user.organization_id,
            DocumentTextExtraction.document_id == document.id,
        )
    )
    if extraction is None:
        raise HTTPException(status_code=409, detail="Document text extraction is unavailable")

    rows = list(
        db.scalars(
            select(DocumentTextSegment)
            .where(
                DocumentTextSegment.organization_id == current_user.organization_id,
                DocumentTextSegment.document_id == document.id,
                DocumentTextSegment.extraction_id == extraction.id,
            )
            .order_by(DocumentTextSegment.segment_index, DocumentTextSegment.id)
            .offset(offset)
            .limit(limit)
        )
    )
    quality = TextExtractionSummary.model_validate(extraction).source_text_quality_state
    return SourceExtractionSegmentsResponse(
        document_id=document.id,
        document_version=document.version_number,
        source_file_hash=document.file_hash,
        extraction_text_hash=extraction.text_hash,
        extraction_method=extraction.extraction_method,
        source_text_quality_state=quality,
        review_disposition="machine_unverified",
        total_segments=extraction.segment_count,
        offset=offset,
        limit=limit,
        segments=[
            SourceExtractionSegment(
                segment_index=segment.segment_index,
                locator_type=segment.locator_type,
                locator_value=segment.locator_value,
                text_preview=segment.text[:_SOURCE_SEGMENT_TEXT_LIMIT],
                source_char_count=len(segment.text),
                text_truncated=len(segment.text) > _SOURCE_SEGMENT_TEXT_LIMIT,
            )
            for segment in rows
        ],
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

    if external_evidence_requires_processing_release(db, document=document):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="External Evidence was admitted without downstream processing authority",
        )

    # Retry is also an operator recovery point. A genuinely active lease remains
    # untouched, while an expired RUNNING extraction is returned to the bounded
    # attempt queue (or terminally failed when its budget is exhausted).
    recover_stale_processing_jobs(
        db,
        document_id=document.id,
        job_type=ProcessingJobType.EXTRACT_TEXT,
        limit=1,
    )
    try:
        job = enqueue_text_extraction(db, document=document, requested_by_id=current_user.id)
    except ExternalEvidenceProcessingAuthorizationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    db.commit()
    db.refresh(job)
    return ProcessingJobResponse.model_validate(job)

# Human-reported OCR transcription discrepancies are audit-only observations.
# They cannot approve facts, source accuracy or the real claims pilot.
from app.modules.processing.ocr_discrepancy import router as ocr_discrepancy_router  # noqa: E402

router.include_router(ocr_discrepancy_router)

# Phase 17.5-Z mounts the explicit processing-release endpoints on this router.
from app.modules.external_document_sources import processing_release_router as _processing_release_router  # noqa: E402,F401
