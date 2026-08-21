from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_final_production_readiness.schemas import (
    AIFinalProductionReadinessClaimEvidenceCreate,
    AIFinalProductionReadinessControlEvidenceCreate,
    AIFinalProductionReadinessCreate,
    AIFinalProductionReadinessDashboard,
    AIFinalProductionReadinessDecision,
    AIFinalProductionReadinessFinalize,
    AIFinalProductionReadinessResponse,
    AIFinalProductionReadinessReviewWrite,
)
from app.modules.ai_final_production_readiness.service import (
    create_assessment,
    decide_outcome,
    finalize_assessment,
    get_assessment,
    list_assessments,
    record_claim_evidence,
    record_control_evidence,
    record_review,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-final-production-readiness", tags=["ai-final-production-readiness"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AIFinalProductionReadinessDashboard)
def dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return AIFinalProductionReadinessDashboard(assessments=list_assessments(db, current_user.organization_id))


@router.post("/assessments", response_model=AIFinalProductionReadinessResponse, status_code=201)
def assessment_create(payload: AIFinalProductionReadinessCreate, manager: Manager,
                      db: Annotated[Session, Depends(get_db)]):
    return create_assessment(db, manager, payload)


@router.post("/assessments/{assessment_id}/claims", response_model=AIFinalProductionReadinessResponse, status_code=201)
def assessment_claim_evidence(assessment_id: UUID, payload: AIFinalProductionReadinessClaimEvidenceCreate,
                              manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_claim_evidence(
        db, manager, get_assessment(db, manager.organization_id, assessment_id), payload
    )


@router.post("/assessments/{assessment_id}/controls", response_model=AIFinalProductionReadinessResponse, status_code=201)
def assessment_control_evidence(assessment_id: UUID, payload: AIFinalProductionReadinessControlEvidenceCreate,
                                manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_control_evidence(
        db, manager, get_assessment(db, manager.organization_id, assessment_id), payload
    )


@router.post("/assessments/{assessment_id}/finalize", response_model=AIFinalProductionReadinessResponse)
def assessment_finalize(assessment_id: UUID, payload: AIFinalProductionReadinessFinalize,
                        manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return finalize_assessment(
        db, manager, get_assessment(db, manager.organization_id, assessment_id),
        payload.confirm_finalize, payload.note,
    )


@router.post("/assessments/{assessment_id}/reviews", response_model=AIFinalProductionReadinessResponse)
def assessment_review(assessment_id: UUID, payload: AIFinalProductionReadinessReviewWrite,
                      manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_review(
        db, manager, get_assessment(db, manager.organization_id, assessment_id),
        payload.review_role, payload.action, payload.evidence_reference, payload.note,
    )


@router.post("/assessments/{assessment_id}/decision", response_model=AIFinalProductionReadinessResponse)
def assessment_decision(assessment_id: UUID, payload: AIFinalProductionReadinessDecision,
                        admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return decide_outcome(
        db, admin, get_assessment(db, admin.organization_id, assessment_id),
        payload.outcome, payload.confirm_recommendation_only, payload.note,
    )
