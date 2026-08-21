from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_near_universal_outcomes.schemas import (
    AINearUniversalOutcomeBusinessCreate,
    AINearUniversalOutcomeCreate,
    AINearUniversalOutcomeDashboard,
    AINearUniversalOutcomeDecision,
    AINearUniversalOutcomeFinalize,
    AINearUniversalOutcomeObservationCreate,
    AINearUniversalOutcomeResponse,
    AINearUniversalOutcomeReviewWrite,
)
from app.modules.ai_near_universal_outcomes.service import (
    create_assessment,
    decide_outcome,
    finalize_assessment,
    get_assessment,
    list_assessments,
    record_business_evidence,
    record_observation,
    record_review,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-near-universal-outcomes", tags=["ai-near-universal-outcomes"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AINearUniversalOutcomeDashboard)
def dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return AINearUniversalOutcomeDashboard(assessments=list_assessments(db, current_user.organization_id))


@router.post("/assessments", response_model=AINearUniversalOutcomeResponse, status_code=201)
def assessment_create(payload: AINearUniversalOutcomeCreate, manager: Manager,
                      db: Annotated[Session, Depends(get_db)]):
    return create_assessment(db, manager, payload)


@router.post("/assessments/{assessment_id}/observations", response_model=AINearUniversalOutcomeResponse, status_code=201)
def assessment_observation(assessment_id: UUID, payload: AINearUniversalOutcomeObservationCreate,
                           manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_observation(db, manager, get_assessment(db, manager.organization_id, assessment_id), payload)


@router.post("/assessments/{assessment_id}/business-evidence", response_model=AINearUniversalOutcomeResponse, status_code=201)
def assessment_business_evidence(assessment_id: UUID, payload: AINearUniversalOutcomeBusinessCreate,
                                 manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_business_evidence(db, manager, get_assessment(db, manager.organization_id, assessment_id), payload)


@router.post("/assessments/{assessment_id}/finalize", response_model=AINearUniversalOutcomeResponse)
def assessment_finalize(assessment_id: UUID, payload: AINearUniversalOutcomeFinalize,
                        manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return finalize_assessment(
        db, manager, get_assessment(db, manager.organization_id, assessment_id),
        payload.confirm_finalize, payload.note,
    )


@router.post("/assessments/{assessment_id}/reviews", response_model=AINearUniversalOutcomeResponse)
def assessment_review(assessment_id: UUID, payload: AINearUniversalOutcomeReviewWrite,
                      manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_review(
        db, manager, get_assessment(db, manager.organization_id, assessment_id),
        payload.review_role, payload.action, payload.evidence_reference, payload.note,
    )


@router.post("/assessments/{assessment_id}/decision", response_model=AINearUniversalOutcomeResponse)
def assessment_decision(assessment_id: UUID, payload: AINearUniversalOutcomeDecision,
                        admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return decide_outcome(
        db, admin, get_assessment(db, admin.organization_id, assessment_id),
        payload.outcome, payload.confirm_recommendation_only, payload.note,
    )
