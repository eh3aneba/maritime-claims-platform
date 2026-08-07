from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.security import get_document_for_tenant
from app.modules.processing.schemas import DocumentProcessingSummary, ProcessingJobResponse
from app.modules.processing.service import enqueue_text_extraction, get_processing_summary

router = APIRouter(prefix="/claims/{claim_id}/documents/{document_id}/processing", tags=["document-processing"])


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
    return DocumentProcessingSummary(
        job=ProcessingJobResponse.model_validate(job) if job else None,
        text_extraction=extraction,
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
    job = enqueue_text_extraction(db, document=document, requested_by_id=current_user.id)
    db.commit()
    db.refresh(job)
    return ProcessingJobResponse.model_validate(job)
