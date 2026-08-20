from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway.base import AIProviderUnavailable
from app.ai.gateway.registry import get_ai_provider
from app.core.config import get_settings
from app.db.session import get_db
from app.modules.ai_governance.service import require_external_ai_runtime_authorization
from app.modules.ai_limited_production.service import reserve_run_if_limited_production
from app.modules.ai_private_pilot.service import reserve_run_if_private_pilot
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
    if provider.name == "openai":
        require_external_ai_runtime_authorization(
            db,
            organization_id=current_user.organization_id,
            document=document,
            expected_document_type="chief_engineer_report",
            input_char_count=text_extraction.char_count,
            requested_by_id=current_user.id,
        )
    job = enqueue_processing_job(
        db,
        document=document,
        requested_by_id=current_user.id,
        job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
    )
    if provider.name == "openai":
        db.flush()
        if settings.app_env.lower().strip() == "production":
            reserve_run_if_limited_production(
                db, user=current_user, document=document,
                expected_document_type="chief_engineer_report",
                input_char_count=text_extraction.char_count, processing_job_id=job.id)
        else:
            reserve_run_if_private_pilot(
                db, user=current_user, document=document,
                expected_document_type="chief_engineer_report",
                input_char_count=text_extraction.char_count, processing_job_id=job.id)
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
    if provider.name == "openai":
        require_external_ai_runtime_authorization(
            db,
            organization_id=current_user.organization_id,
            document=document,
            expected_document_type="engine_log",
            input_char_count=text_extraction.char_count,
            requested_by_id=current_user.id,
        )
    job = enqueue_processing_job(
        db,
        document=document,
        requested_by_id=current_user.id,
        job_type=ProcessingJobType.AI_EXTRACT_ENGINE_LOG,
    )
    if provider.name == "openai":
        db.flush()
        if settings.app_env.lower().strip() == "production":
            reserve_run_if_limited_production(
                db, user=current_user, document=document,
                expected_document_type="engine_log",
                input_char_count=text_extraction.char_count, processing_job_id=job.id)
        else:
            reserve_run_if_private_pilot(
                db, user=current_user, document=document,
                expected_document_type="engine_log",
                input_char_count=text_extraction.char_count, processing_job_id=job.id)
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


def _enqueue_specialized_intelligence(
    *,
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Session,
    job_type: ProcessingJobType,
) -> dict[str, str]:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(db, document_id=document_id, claim_id=claim.id, organization_id=current_user.organization_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    text_extraction = db.scalar(select(DocumentTextExtraction).where(
        DocumentTextExtraction.document_id == document.id,
        DocumentTextExtraction.organization_id == current_user.organization_id,
    ))
    if text_extraction is None or text_extraction.char_count <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document text extraction must complete before AI intelligence can run.")
    if text_extraction.requires_ocr:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document requires OCR before AI intelligence can run.")
    try:
        provider = get_ai_provider()
        if provider.name == "disabled":
            raise AIProviderUnavailable("AI provider is disabled. Configure AI_PROVIDER before enabling document intelligence.")
    except AIProviderUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if document.confidentiality_level == ConfidentialityLevel.RESTRICTED and provider.name == "openai" and not settings.allow_external_ai_restricted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Restricted documents cannot be sent to the configured external AI provider unless explicitly enabled.")
    if provider.name == "openai":
        expected_document_type = {
            ProcessingJobType.AI_EXTRACT_RUNNING_HOURS: "running_hours_record",
            ProcessingJobType.AI_EXTRACT_PMS_HISTORY: "pms_record",
            ProcessingJobType.AI_EXTRACT_WORKSHOP_REPORT: "workshop_report",
            ProcessingJobType.AI_EXTRACT_QUOTATION: "quotation",
            ProcessingJobType.AI_EXTRACT_INVOICE: "invoice",
        }[job_type]
        require_external_ai_runtime_authorization(
            db,
            organization_id=current_user.organization_id,
            document=document,
            expected_document_type=expected_document_type,
            input_char_count=text_extraction.char_count,
            requested_by_id=current_user.id,
        )
    job = enqueue_processing_job(db, document=document, requested_by_id=current_user.id, job_type=job_type)
    db.commit(); db.refresh(job)
    return {"job_id": str(job.id), "status": job.status.value}


@router.post("/running-hours", status_code=status.HTTP_202_ACCEPTED)
def enqueue_running_hours_intelligence(claim_id: UUID, document_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return _enqueue_specialized_intelligence(claim_id=claim_id, document_id=document_id, current_user=current_user, db=db, job_type=ProcessingJobType.AI_EXTRACT_RUNNING_HOURS)


@router.post("/pms-history", status_code=status.HTTP_202_ACCEPTED)
def enqueue_pms_history_intelligence(claim_id: UUID, document_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return _enqueue_specialized_intelligence(claim_id=claim_id, document_id=document_id, current_user=current_user, db=db, job_type=ProcessingJobType.AI_EXTRACT_PMS_HISTORY)


@router.post("/workshop-report", status_code=status.HTTP_202_ACCEPTED)
def enqueue_workshop_report_intelligence(claim_id: UUID, document_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return _enqueue_specialized_intelligence(claim_id=claim_id, document_id=document_id, current_user=current_user, db=db, job_type=ProcessingJobType.AI_EXTRACT_WORKSHOP_REPORT)


@router.post("/quotation", status_code=status.HTTP_202_ACCEPTED)
def enqueue_quotation_intelligence(claim_id: UUID, document_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return _enqueue_specialized_intelligence(claim_id=claim_id, document_id=document_id, current_user=current_user, db=db, job_type=ProcessingJobType.AI_EXTRACT_QUOTATION)

@router.post("/invoice", status_code=status.HTTP_202_ACCEPTED)
def enqueue_invoice_intelligence(claim_id: UUID, document_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return _enqueue_specialized_intelligence(claim_id=claim_id, document_id=document_id, current_user=current_user, db=db, job_type=ProcessingJobType.AI_EXTRACT_INVOICE)
