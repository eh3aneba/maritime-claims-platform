from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.severity_reserve.models import SeverityReserveEvaluation
from app.modules.severity_reserve.schemas import (
    SeverityReserveDashboardResponse,
    SeverityReserveDecisionResponse,
    SeverityReserveDecisionWrite,
    SeverityReserveSnapshotResponse,
)
from app.modules.severity_reserve.service import (
    build_severity_reserve_support,
    dashboard_response,
    record_decision,
    snapshot_response,
)

router = APIRouter(prefix="/claims/{claim_id}/severity-reserve", tags=["severity-reserve"])


@router.get("", response_model=SeverityReserveDashboardResponse)
def get_dashboard(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return dashboard_response(db, claim=claim)


@router.post("/build", response_model=SeverityReserveSnapshotResponse, status_code=status.HTTP_201_CREATED)
def build_support(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    snapshot = build_severity_reserve_support(db, claim=claim, user=current_user)
    return snapshot_response(db, snapshot)


@router.post(
    "/evaluations/{evaluation_id}/decision",
    response_model=SeverityReserveDecisionResponse,
)
def review_evaluation(
    claim_id: UUID,
    evaluation_id: UUID,
    payload: SeverityReserveDecisionWrite,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    evaluation = db.get(SeverityReserveEvaluation, evaluation_id)
    if evaluation is None or evaluation.organization_id != claim.organization_id or evaluation.claim_id != claim.id:
        raise HTTPException(status_code=404, detail="Severity/reserve evaluation not found")
    try:
        return record_decision(db, claim=claim, evaluation=evaluation, payload=payload, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
