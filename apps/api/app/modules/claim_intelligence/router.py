from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claim_intelligence.models import (
    ClaimIntelligenceItem,
    ClaimIntelligenceItemDecision,
    ClaimIntelligenceSnapshot,
)
from app.modules.claim_intelligence.schemas import (
    ClaimIntelligenceDashboardResponse,
    ClaimIntelligenceDecisionResponse,
    ClaimIntelligenceDecisionWrite,
    ClaimIntelligenceSnapshotResponse,
)
from app.modules.claim_intelligence.service import (
    build_claim_intelligence,
    dashboard_response,
    record_item_decision,
    snapshot_response,
)
from app.modules.claims.security import get_claim_for_tenant

router = APIRouter(prefix="/claims/{claim_id}/intelligence", tags=["claim-intelligence"])


@router.get("", response_model=ClaimIntelligenceDashboardResponse)
def get_intelligence(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ClaimIntelligenceDashboardResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return ClaimIntelligenceDashboardResponse.model_validate(dashboard_response(db, claim=claim))


@router.post("/build", response_model=ClaimIntelligenceSnapshotResponse, status_code=status.HTTP_201_CREATED)
def build_intelligence(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ClaimIntelligenceSnapshotResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    try:
        snapshot = build_claim_intelligence(db, claim=claim, user=current_user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ClaimIntelligenceSnapshotResponse.model_validate(snapshot_response(db, snapshot))


@router.post("/items/{item_id}/decision", response_model=ClaimIntelligenceDecisionResponse)
def review_intelligence_item(
    claim_id: UUID,
    item_id: UUID,
    payload: ClaimIntelligenceDecisionWrite,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ClaimIntelligenceDecisionResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    item = db.scalar(select(ClaimIntelligenceItem).where(
        ClaimIntelligenceItem.id == item_id,
        ClaimIntelligenceItem.organization_id == current_user.organization_id,
        ClaimIntelligenceItem.claim_id == claim.id,
    ))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intelligence item not found")

    latest_snapshot_id = db.scalar(
        select(ClaimIntelligenceSnapshot.id)
        .where(
            ClaimIntelligenceSnapshot.organization_id == current_user.organization_id,
            ClaimIntelligenceSnapshot.claim_id == claim.id,
        )
        .order_by(ClaimIntelligenceSnapshot.snapshot_version.desc())
        .limit(1)
    )
    if latest_snapshot_id != item.snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Intelligence item belongs to a superseded snapshot; review the latest intelligence snapshot instead",
        )

    if payload.convert_to_task:
        existing_task_id = db.scalar(
            select(ClaimIntelligenceItemDecision.converted_task_id)
            .where(
                ClaimIntelligenceItemDecision.organization_id == current_user.organization_id,
                ClaimIntelligenceItemDecision.claim_id == claim.id,
                ClaimIntelligenceItemDecision.item_id == item.id,
                ClaimIntelligenceItemDecision.converted_task_id.is_not(None),
            )
            .order_by(ClaimIntelligenceItemDecision.decision_number.desc())
            .limit(1)
        )
        if existing_task_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A controlled claim task has already been created from this intelligence item",
            )

    try:
        decision = record_item_decision(db, claim=claim, item=item, user=current_user, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ClaimIntelligenceDecisionResponse.model_validate(decision)
