from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.recovery_timebar.maturity import (
    MATURITY_DISCLAIMER,
    counterparty_history,
    counterparty_response,
    create_counterparty,
    create_scenario,
    current_counterparties,
    current_scenarios,
    review_response,
    revise_counterparty,
    revise_scenario,
    scenario_history,
)
from app.modules.recovery_timebar.maturity_context import review_scenario, scenario_response
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation
from app.modules.recovery_timebar.schemas import (
    RecoveryCounterpartyResponse,
    RecoveryCounterpartyRevisionWrite,
    RecoveryCounterpartyWrite,
    RecoveryMaturityDashboardResponse,
    RecoveryTimebarDashboardResponse,
    RecoveryTimebarDecisionResponse,
    RecoveryTimebarDecisionWrite,
    RecoveryTimebarSnapshotResponse,
    TimebarScenarioResponse,
    TimebarScenarioRevisionWrite,
    TimebarScenarioReviewResponse,
    TimebarScenarioReviewWrite,
    TimebarScenarioWrite,
)
from app.modules.recovery_timebar.service import (
    build_recovery_timebar,
    dashboard_response,
    record_decision,
    snapshot_response,
)
from app.modules.rules.service import evaluate_claim_rules
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims/{claim_id}/recovery-timebar", tags=["recovery-timebar"])
RecoveryEditor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER, UserRole.CLAIMS_HANDLER)),
]
RecoveryLegalReviewer = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER)),
]


def _claim(db: Session, claim_id: UUID, organization_id: UUID):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return claim


@router.get("", response_model=RecoveryTimebarDashboardResponse)
def get_recovery_timebar(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryTimebarDashboardResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    return RecoveryTimebarDashboardResponse.model_validate(dashboard_response(db, claim=claim))


@router.post("/build", response_model=RecoveryTimebarSnapshotResponse, status_code=status.HTTP_201_CREATED)
def build_recovery_timebar_intelligence(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryTimebarSnapshotResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    try:
        evaluate_claim_rules(db, claim=claim, user=current_user, trigger="recovery_timebar")
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
    claim = _claim(db, claim_id, current_user.organization_id)
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


@router.get("/maturity", response_model=RecoveryMaturityDashboardResponse)
def get_recovery_maturity(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryMaturityDashboardResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    return RecoveryMaturityDashboardResponse(
        claim_id=claim.id,
        counterparties=[counterparty_response(db, row) for row in current_counterparties(db, claim=claim)],
        scenarios=[scenario_response(db, row) for row in current_scenarios(db, claim=claim)],
        disclaimer=MATURITY_DISCLAIMER,
    )


@router.post("/counterparties", response_model=RecoveryCounterpartyResponse, status_code=status.HTTP_201_CREATED)
def create_recovery_counterparty(
    claim_id: UUID,
    payload: RecoveryCounterpartyWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryCounterpartyResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = create_counterparty(db, claim=claim, user=editor, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryCounterpartyResponse(**counterparty_response(db, row))


@router.post("/counterparties/{counterparty_key}/revisions", response_model=RecoveryCounterpartyResponse, status_code=status.HTTP_201_CREATED)
def revise_recovery_counterparty(
    claim_id: UUID,
    counterparty_key: UUID,
    payload: RecoveryCounterpartyRevisionWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryCounterpartyResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = revise_counterparty(
            db,
            claim=claim,
            user=editor,
            counterparty_key=counterparty_key,
            payload=payload,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryCounterpartyResponse(**counterparty_response(db, row))


@router.get("/counterparties/{counterparty_key}/history", response_model=list[RecoveryCounterpartyResponse])
def get_recovery_counterparty_history(
    claim_id: UUID,
    counterparty_key: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[RecoveryCounterpartyResponse]:
    claim = _claim(db, claim_id, current_user.organization_id)
    return [
        RecoveryCounterpartyResponse(**counterparty_response(db, row))
        for row in counterparty_history(db, claim=claim, counterparty_key=counterparty_key)
    ]


@router.post("/scenarios", response_model=TimebarScenarioResponse, status_code=status.HTTP_201_CREATED)
def create_timebar_scenario(
    claim_id: UUID,
    payload: TimebarScenarioWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> TimebarScenarioResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = create_scenario(db, claim=claim, user=editor, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TimebarScenarioResponse(**scenario_response(db, row))


@router.post("/scenarios/{scenario_key}/revisions", response_model=TimebarScenarioResponse, status_code=status.HTTP_201_CREATED)
def revise_timebar_scenario(
    claim_id: UUID,
    scenario_key: UUID,
    payload: TimebarScenarioRevisionWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> TimebarScenarioResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = revise_scenario(db, claim=claim, user=editor, scenario_key=scenario_key, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TimebarScenarioResponse(**scenario_response(db, row))


@router.get("/scenarios/{scenario_key}/history", response_model=list[TimebarScenarioResponse])
def get_timebar_scenario_history(
    claim_id: UUID,
    scenario_key: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[TimebarScenarioResponse]:
    claim = _claim(db, claim_id, current_user.organization_id)
    return [
        TimebarScenarioResponse(**scenario_response(db, row))
        for row in scenario_history(db, claim=claim, scenario_key=scenario_key)
    ]


@router.post("/scenarios/{scenario_id}/review", response_model=TimebarScenarioReviewResponse)
def review_timebar_scenario(
    claim_id: UUID,
    scenario_id: UUID,
    payload: TimebarScenarioReviewWrite,
    reviewer: RecoveryLegalReviewer,
    db: Annotated[Session, Depends(get_db)],
) -> TimebarScenarioReviewResponse:
    claim = _claim(db, claim_id, reviewer.organization_id)
    try:
        row = review_scenario(db, claim=claim, user=reviewer, scenario_id=scenario_id, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TimebarScenarioReviewResponse(**review_response(row))
