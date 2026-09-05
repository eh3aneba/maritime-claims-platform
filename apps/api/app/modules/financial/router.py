from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.financial.models import FinancialFlag
from app.modules.financial.schemas import (
    CostReviewDecisionRead,
    CostStatusUpdate,
    FinancialFlagResolve,
    FinancialReviewResponse,
)
from app.modules.financial.service import (
    CostReviewConflictError,
    build_financial_review,
    record_cost_review_decision,
    resolve_financial_flag,
)
from app.modules.users.models import User, UserRole


router = APIRouter(prefix="/claims/{claim_id}/financial-review", tags=["financial-review"])
FinancialReviewer = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER, UserRole.CLAIMS_HANDLER)),
]


@router.get("", response_model=FinancialReviewResponse)
def get_financial_review(
    claim_id: UUID,
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
    result = build_financial_review(db, claim=claim, user_id=current_user.id)
    db.commit()
    return result


@router.post(
    "/items/{item_id}/status",
    response_model=CostReviewDecisionRead,
)
def change_cost_status(
    claim_id: UUID,
    item_id: UUID,
    payload: CostStatusUpdate,
    current_user: FinancialReviewer,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(
        db,
        claim_id=claim_id,
        organization_id=current_user.organization_id,
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    try:
        decision = record_cost_review_decision(
            db,
            claim_id=claim.id,
            organization_id=claim.organization_id,
            item_id=item_id,
            status=payload.status,
            reason=payload.reason,
            expected_state_fingerprint=payload.expected_state_fingerprint,
            expected_state_version=payload.expected_state_version,
            confirm_re_review=payload.confirm_re_review,
            user_id=current_user.id,
        )
    except CostReviewConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(decision)
    return decision


@router.post("/flags/{flag_id}/resolve")
def resolve_flag(
    claim_id: UUID,
    flag_id: UUID,
    payload: FinancialFlagResolve,
    current_user: FinancialReviewer,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(
        db,
        claim_id=claim_id,
        organization_id=current_user.organization_id,
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    flag = db.get(FinancialFlag, flag_id)
    if (
        flag is None
        or flag.claim_id != claim.id
        or flag.organization_id != claim.organization_id
    ):
        raise HTTPException(status_code=404, detail="Financial flag not found")
    resolve_financial_flag(
        db,
        claim=claim,
        flag=flag,
        status=payload.status,
        note=payload.note,
        user_id=current_user.id,
    )
    db.commit()
    return {"id": str(flag.id), "status": flag.status.value}
