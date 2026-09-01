from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.evidence_search.qa_schemas import (
    ClaimQaRequest,
    ClaimQaResponse,
    ClaimQaSynthesisRequest,
    ClaimQaSynthesisResponse,
)
from app.modules.evidence_search.qa_service import answer_claim_question
from app.modules.evidence_search.qa_synthesis_service import synthesize_claim_question
from app.modules.evidence_search.schemas import EvidenceSearchRequest, EvidenceSearchResponse
from app.modules.evidence_search.service import search_claim_evidence

router = APIRouter(prefix="/claims/{claim_id}/evidence-search", tags=["evidence-search"])


@router.post("", response_model=EvidenceSearchResponse)
def search_evidence(
    claim_id: UUID,
    payload: EvidenceSearchRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(
        db,
        claim_id=claim_id,
        organization_id=current_user.organization_id,
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return search_claim_evidence(db, claim=claim, user=current_user, payload=payload)


@router.post("/qa", response_model=ClaimQaResponse)
def answer_question(
    claim_id: UUID,
    payload: ClaimQaRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(
        db,
        claim_id=claim_id,
        organization_id=current_user.organization_id,
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return answer_claim_question(db, claim=claim, user=current_user, payload=payload)


@router.post("/qa/synthesize", response_model=ClaimQaSynthesisResponse)
def synthesize_question(
    claim_id: UUID,
    payload: ClaimQaSynthesisRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(
        db,
        claim_id=claim_id,
        organization_id=current_user.organization_id,
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return synthesize_claim_question(db, claim=claim, user=current_user, payload=payload)
