from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway.base import AIProviderUnavailable
from app.ai.gateway.registry import get_ai_provider
from app.core.config import get_settings
from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import ConfidentialityLevel
from app.modules.documents.security import get_document_for_tenant
from app.modules.intelligence.schemas import AIRunResponse, DocumentExtractionResponse, DocumentIntelligenceResponse, EngineLogEventCandidateResponse, EngineLogEventsResponse
from app.modules.intelligence.service import get_engine_log_event_candidates, get_latest_ai_result
from app.modules.processing.models import DocumentTextExtraction, ProcessingJobType
from app.modules.processing.service import enqueue_processing_job

settings = get_settings()

router = APIRouter(prefix="/claims/{claim_id}/documents/{document_id}/intelligence", tags=["document-intelligence"])


@router.get("", response_model=DocumentIntelligenceResponse)
def intelligence_summary(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentIntelligenceResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    run, extractions = get_latest_ai_result(db, document_id=document.id, organization_id=current_user.organization_id)
    return DocumentIntelligenceResponse(
        run=AIRunResponse.model_validate(run) if run else None,
        extractions=[DocumentExtractionResponse.model_validate(item) for item in extractions],
    )


@router.post("/ce-report", status_code=status.HTTP_202_ACCEPTED)
def enqueue_ce_report_intelligence(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    text_extraction = db.scalar(
        select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == document.id,
            DocumentTextExtraction.organization_id == current_user.organization_id,
        )
    )
    if text_extraction is None or text_extraction.char_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document text extraction must complete before AI intelligence can run.",
        )
    if text_extraction.requires_ocr:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document requires OCR before AI intelligence can run.",
        )
    try:
        provider = get_ai_provider()
        if provider.name == "disabled":
            raise AIProviderUnavailable("AI provider is disabled. Configure AI_PROVIDER before enabling document intelligence.")
    except AIProviderUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if (
        document.confidentiality_level == ConfidentialityLevel.RESTRICTED
        and provider.name == "openai"
        and not settings.allow_external_ai_restricted
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Restricted documents cannot be sent to the configured external AI provider unless explicitly enabled.",
        )
    job = enqueue_processing_job(
        db,
        document=document,
        requested_by_id=current_user.id,
        job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
    )
    db.commit()
    db.refresh(job)
    return {"job_id": str(job.id), "status": job.status.value}


@router.post("/engine-log", status_code=status.HTTP_202_ACCEPTED)
def enqueue_engine_log_intelligence(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    text_extraction = db.scalar(
        select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == document.id,
            DocumentTextExtraction.organization_id == current_user.organization_id,
        )
    )
    if text_extraction is None or text_extraction.char_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document text extraction must complete before AI intelligence can run.",
        )
    if text_extraction.requires_ocr:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document requires OCR before AI intelligence can run.",
        )
    try:
        provider = get_ai_provider()
        if provider.name == "disabled":
            raise AIProviderUnavailable("AI provider is disabled. Configure AI_PROVIDER before enabling document intelligence.")
    except AIProviderUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if (
        document.confidentiality_level == ConfidentialityLevel.RESTRICTED
        and provider.name == "openai"
        and not settings.allow_external_ai_restricted
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Restricted documents cannot be sent to the configured external AI provider unless explicitly enabled.",
        )
    job = enqueue_processing_job(
        db,
        document=document,
        requested_by_id=current_user.id,
        job_type=ProcessingJobType.AI_EXTRACT_ENGINE_LOG,
    )
    db.commit()
    db.refresh(job)
    return {"job_id": str(job.id), "status": job.status.value}


@router.get("/engine-log/events", response_model=EngineLogEventsResponse)
def engine_log_event_candidates(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> EngineLogEventsResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    run, events = get_engine_log_event_candidates(
        db, document_id=document.id, organization_id=current_user.organization_id
    )
    return EngineLogEventsResponse(
        run=AIRunResponse.model_validate(run) if run else None,
        events=[EngineLogEventCandidateResponse.model_validate(item) for item in events],
    )
