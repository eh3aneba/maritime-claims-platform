from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.service import ClaimNotFoundError, get_claim
from app.modules.documents.models import Document
from app.modules.policy_intelligence.extractor import run_local_policy_extraction
from app.modules.policy_intelligence.schemas import (
    PolicyExtractionResponse,
    PolicyIntelligenceResponse,
)
from app.modules.policy_intelligence.service import build_policy_intelligence


router = APIRouter(
    prefix="/claims/{claim_id}/policy-intelligence",
    tags=["policy-intelligence"],
)


@router.get("", response_model=PolicyIntelligenceResponse)
def get_policy_intelligence(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PolicyIntelligenceResponse:
    try:
        return build_policy_intelligence(
            db,
            claim_id=claim_id,
            organization_id=current_user.organization_id,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found",
        ) from exc


@router.post(
    "/documents/{document_id}/extract",
    response_model=PolicyExtractionResponse,
    status_code=status.HTTP_201_CREATED,
)
def extract_policy_terms(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PolicyExtractionResponse:
    try:
        claim = get_claim(
            db,
            claim_id=claim_id,
            organization_id=current_user.organization_id,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found",
        ) from exc
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == current_user.organization_id,
            Document.claim_id == claim.id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    try:
        return run_local_policy_extraction(
            db,
            claim=claim,
            document=document,
            user=current_user,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
