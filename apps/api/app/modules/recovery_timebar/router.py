from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation
from app.modules.recovery_timebar.schemas import (
    RecoveryTimebarDashboardResponse,
    RecoveryTimebarDecisionResponse,
    RecoveryTimebarDecisionWrite,
    RecoveryTimebarSnapshotResponse,
)
from app.modules.recovery_timebar.service import (
    build_recovery_timebar,
    dashboard_response,
    record_decision,
    snapshot_response,
)

router = APIRouter(prefix="/claims/{claim_id}/recovery-timebar", tags=["recovery-timebar"])


@router.get("", response_model=RecoveryTimebarDashboardResponse)
def get_recovery_timebar(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryTimebarDashboardResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return RecoveryTimebarDashboardResponse.model_validate(dashboard_response(db, claim=claim))


@router.post("/build", response_model=RecoveryTimebarSnapshotResponse, status_code=status.HTTP_201_CREATED)
def build_recovery_timebar_intelligence(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryTimebarSnapshotResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    try:
        snapshot = build_recovery_timebar(db, claim=claim, user=current_user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryTimebarSnapshotResponse.model_validate(snapshot_response(db, snapshot))


@router.post("/evaluations/{evaluation_id}/decision", response_model=RecoveryTimebarDecisionResponse)
def review_recovery_timebar_evaluation(
    claim_id: UUID,
    evaluation_id: UUID,
    payload: RecoveryTimebarDecisionWrite,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryTimebarDecisionResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    evaluation = db.scalar(
        select(RecoveryTimebarEvaluation).where(
            RecoveryTimebarEvaluation.id == evaluation_id,
            RecoveryTimebarEvaluation.organization_id == current_user.organization_id,
            RecoveryTimebarEvaluation.claim_id == claim.id,
        )
    )
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery/time-bar evaluation not found")
    try:
        decision = record_decision(db, claim=claim, evaluation=evaluation, payload=payload, user=current_user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryTimebarDecisionResponse.model_validate(decision)
