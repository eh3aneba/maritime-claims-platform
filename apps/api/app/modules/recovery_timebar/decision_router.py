from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.recovery_timebar.decision_lineage import (
    DECISION_DISCLAIMER,
    action_history,
    action_response,
    append_action,
    create_decision,
    current_decisions,
    decision_history,
    decision_response,
    revise_decision,
)
from app.modules.recovery_timebar.decision_schemas import (
    RecoveryActionLogResponse,
    RecoveryActionLogWrite,
    RecoveryDecisionDashboardResponse,
    RecoveryPursuitDecisionResponse,
    RecoveryPursuitDecisionRevisionWrite,
    RecoveryPursuitDecisionWrite,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims/{claim_id}/recovery-timebar", tags=["recovery-timebar"])
RecoveryEditor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER, UserRole.CLAIMS_HANDLER)),
]


def _claim(db: Session, claim_id: UUID, organization_id: UUID):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return claim


@router.get("/decisions", response_model=RecoveryDecisionDashboardResponse)
def get_recovery_decisions(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryDecisionDashboardResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    return RecoveryDecisionDashboardResponse(
        claim_id=claim.id,
        decisions=[
            RecoveryPursuitDecisionResponse(**decision_response(db, claim=claim, row=row))
            for row in current_decisions(db, claim=claim)
        ],
        disclaimer=DECISION_DISCLAIMER,
    )


@router.post("/decisions", response_model=RecoveryPursuitDecisionResponse, status_code=status.HTTP_201_CREATED)
def create_recovery_decision(
    claim_id: UUID,
    payload: RecoveryPursuitDecisionWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryPursuitDecisionResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = create_decision(db, claim=claim, user=editor, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryPursuitDecisionResponse(**decision_response(db, claim=claim, row=row))


@router.post(
    "/decisions/{decision_key}/revisions",
    response_model=RecoveryPursuitDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def revise_recovery_decision(
    claim_id: UUID,
    decision_key: UUID,
    payload: RecoveryPursuitDecisionRevisionWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryPursuitDecisionResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = revise_decision(
            db,
            claim=claim,
            user=editor,
            decision_key=decision_key,
            payload=payload,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryPursuitDecisionResponse(**decision_response(db, claim=claim, row=row))


@router.get("/decisions/{decision_key}/history", response_model=list[RecoveryPursuitDecisionResponse])
def get_recovery_decision_history(
    claim_id: UUID,
    decision_key: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[RecoveryPursuitDecisionResponse]:
    claim = _claim(db, claim_id, current_user.organization_id)
    return [
        RecoveryPursuitDecisionResponse(**decision_response(db, claim=claim, row=row))
        for row in decision_history(db, claim=claim, decision_key=decision_key)
    ]


@router.post(
    "/decisions/{decision_key}/actions",
    response_model=RecoveryActionLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def append_recovery_action(
    claim_id: UUID,
    decision_key: UUID,
    payload: RecoveryActionLogWrite,
    editor: RecoveryEditor,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryActionLogResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    try:
        row = append_action(
            db,
            claim=claim,
            user=editor,
            decision_key=decision_key,
            payload=payload,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RecoveryActionLogResponse(**action_response(row))


@router.get("/decisions/{decision_key}/actions", response_model=list[RecoveryActionLogResponse])
def get_recovery_actions(
    claim_id: UUID,
    decision_key: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[RecoveryActionLogResponse]:
    claim = _claim(db, claim_id, current_user.organization_id)
    return [
        RecoveryActionLogResponse(**action_response(row))
        for row in action_history(db, claim=claim, decision_key=decision_key)
    ]
