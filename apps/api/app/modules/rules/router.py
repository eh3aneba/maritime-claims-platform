from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.rules.schemas import RuleEvaluationResponse, RuleSummaryResponse
from app.modules.rules.service import evaluate_claim_rules, get_rule_summary

router = APIRouter(prefix="/claims/{claim_id}/rules", tags=["rules"])


@router.get("", response_model=RuleSummaryResponse)
def rule_summary(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> RuleSummaryResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return get_rule_summary(db, claim=claim)


@router.post("/evaluate", response_model=RuleEvaluationResponse)
def evaluate_rules(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> RuleEvaluationResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    run = evaluate_claim_rules(db, claim=claim, user=current_user)
    return RuleEvaluationResponse(run_id=run.id, summary=get_rule_summary(db, claim=claim))
