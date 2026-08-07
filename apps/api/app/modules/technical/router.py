from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.technical.schemas import TechnicalReviewResponse
from app.modules.technical.service import build_technical_review

router = APIRouter(prefix="/claims/{claim_id}/technical-review", tags=["technical-review"])


@router.get("", response_model=TechnicalReviewResponse)
def technical_review(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> TechnicalReviewResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return TechnicalReviewResponse.model_validate(build_technical_review(db, claim_id=claim.id, organization_id=current_user.organization_id))
