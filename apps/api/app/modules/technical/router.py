from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.technical.schemas import (
    TechnicalDecisionCreate,
    TechnicalDecisionHistoryResponse,
    TechnicalInvestigationDecisionResponse,
    TechnicalReviewResponse,
)
from app.modules.technical.service import (
    TechnicalDecisionConflictError,
    TechnicalTopicNotFoundError,
    build_technical_review,
    record_technical_decision,
    technical_decision_history,
)

router = APIRouter(prefix="/claims/{claim_id}/technical-review", tags=["technical-review"])


@router.get("", response_model=TechnicalReviewResponse)
def technical_review(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> TechnicalReviewResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return TechnicalReviewResponse.model_validate(build_technical_review(db, claim_id=claim.id, organization_id=current_user.organization_id))


@router.get("/topics/{topic_key}/decisions", response_model=TechnicalDecisionHistoryResponse)
def technical_topic_decision_history(
    claim_id: UUID,
    topic_key: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> TechnicalDecisionHistoryResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    try:
        payload = technical_decision_history(
            db,
            claim_id=claim.id,
            organization_id=current_user.organization_id,
            topic_key=topic_key,
        )
    except TechnicalTopicNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TechnicalDecisionHistoryResponse.model_validate(payload)


@router.post("/topics/{topic_key}/decisions", response_model=TechnicalInvestigationDecisionResponse)
def decide_technical_topic(
    claim_id: UUID,
    topic_key: str,
    payload: TechnicalDecisionCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> TechnicalInvestigationDecisionResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    try:
        decision = record_technical_decision(
            db,
            claim_id=claim.id,
            organization_id=current_user.organization_id,
            topic_key=topic_key,
            action=payload.action,
            note=payload.note,
            expected_state_fingerprint=payload.expected_state_fingerprint,
            expected_state_version=payload.expected_state_version,
            confirm_re_review=payload.confirm_re_review,
            decided_by_id=current_user.id,
        )
        db.commit()
    except TechnicalTopicNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TechnicalDecisionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TechnicalInvestigationDecisionResponse.model_validate(decision)
