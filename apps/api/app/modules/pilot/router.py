from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.pilot.models import PilotCommercialValidation, PilotFeedback, PilotSession
from app.modules.pilot.schemas import PilotCommercialScorecard, PilotCommercialValidationRead, PilotCommercialValidationUpsert, PilotEventCreate, PilotFeedbackCreate, PilotFeedbackRead, PilotMetrics, PilotScorecard, PilotSessionEnd, PilotSessionRead, PilotSessionStart
from app.modules.pilot.service import add_feedback, build_commercial_scorecard, build_scorecard, calculate_metrics, end_session, get_commercial_validation, get_session, record_event, start_session, upsert_commercial_validation

router = APIRouter(prefix="/pilot", tags=["pilot"])


def _session_or_404(db: Session, *, session_id: UUID, organization_id: UUID) -> PilotSession:
    row = get_session(db, session_id=session_id, organization_id=organization_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pilot session not found")
    return row


@router.post("/sessions", response_model=PilotSessionRead)
def start(payload: PilotSessionStart, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    claim = get_claim_for_tenant(db, claim_id=payload.claim_id, organization_id=current_user.organization_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    row = start_session(db, claim=claim, user=current_user, participant_role=payload.participant_role, objective=payload.objective, baseline_assessment_minutes=payload.baseline_assessment_minutes)
    db.commit(); db.refresh(row)
    return row


@router.post("/sessions/{session_id}/end", response_model=PilotSessionRead)
def end(session_id: UUID, payload: PilotSessionEnd, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    try:
        end_session(db, session=row, user=current_user, status=payload.status, note=payload.note)
        db.commit(); db.refresh(row)
        return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/events", status_code=201)
def browser_event(session_id: UUID, payload: PilotEventCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Pilot session is not active")
    event = record_event(db, session=row, user_id=current_user.id, event_type=payload.event_type, source="browser", entity_type=payload.entity_type, entity_id=payload.entity_id, duration_ms=payload.duration_ms, event_data=payload.event_data)
    db.commit(); db.refresh(event)
    return {"id": event.id, "created_at": event.created_at}


@router.post("/sessions/{session_id}/feedback", response_model=PilotFeedbackRead, status_code=201)
def feedback(session_id: UUID, payload: PilotFeedbackCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    item = add_feedback(db, session=row, user=current_user, category=payload.category, severity=payload.severity, verdict=payload.verdict, rating=payload.rating, comment=payload.comment, entity_type=payload.entity_type, entity_id=payload.entity_id)
    db.commit(); db.refresh(item)
    return item


@router.get("/sessions/{session_id}/feedback", response_model=list[PilotFeedbackRead])
def feedback_list(session_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    return list(db.scalars(select(PilotFeedback).where(PilotFeedback.session_id == session_id, PilotFeedback.organization_id == current_user.organization_id).order_by(PilotFeedback.created_at.asc())))


@router.get("/sessions/{session_id}/metrics", response_model=PilotMetrics)
def metrics(session_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    return calculate_metrics(db, session=row)


@router.get("/sessions/{session_id}/scorecard", response_model=PilotScorecard)
def scorecard(session_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    return build_scorecard(db, session=row)


@router.get("/sessions/{session_id}/commercial-validation", response_model=PilotCommercialValidationRead | None)
def commercial_validation_get(session_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    return get_commercial_validation(db, session_id=session_id, organization_id=current_user.organization_id)


@router.put("/sessions/{session_id}/commercial-validation", response_model=PilotCommercialValidationRead)
def commercial_validation_put(session_id: UUID, payload: PilotCommercialValidationUpsert, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    try:
        result = upsert_commercial_validation(db, session=row, user=current_user, values=payload.model_dump())
        db.commit(); db.refresh(result)
        return result
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/commercial-scorecard", response_model=PilotCommercialScorecard)
def commercial_scorecard(session_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = _session_or_404(db, session_id=session_id, organization_id=current_user.organization_id)
    return build_commercial_scorecard(db, session=row)
