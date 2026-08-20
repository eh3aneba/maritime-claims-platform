from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_evaluation.schemas import (
    AIEvaluationCaseCreate, AIEvaluationDashboard, AIEvaluationDecision,
    AIEvaluationFinalize, AIEvaluationReviewWrite, AIEvaluationRevoke,
    AIEvaluationSuiteCreate, AIEvaluationSuiteResponse,
)
from app.modules.ai_evaluation.service import (
    create_suite, decide_promotion, finalize_suite, get_suite, list_suites,
    record_case, record_review, revoke_promotion,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-evaluation", tags=["ai-evaluation"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AIEvaluationDashboard)
def evaluation_dashboard(current_user: CurrentUser,
                         db: Annotated[Session, Depends(get_db)]):
    return AIEvaluationDashboard(suites=list_suites(db, current_user.organization_id))


@router.post("/suites", response_model=AIEvaluationSuiteResponse, status_code=201)
def evaluation_suite_create(payload: AIEvaluationSuiteCreate, manager: Manager,
                            db: Annotated[Session, Depends(get_db)]):
    return create_suite(db, manager, payload)


@router.post("/suites/{suite_id}/cases", response_model=AIEvaluationSuiteResponse,
             status_code=201)
def evaluation_case_create(suite_id: UUID, payload: AIEvaluationCaseCreate,
                           manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_case(
        db, manager, get_suite(db, manager.organization_id, suite_id), payload)


@router.post("/suites/{suite_id}/finalize", response_model=AIEvaluationSuiteResponse)
def evaluation_finalize(suite_id: UUID, payload: AIEvaluationFinalize,
                        manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return finalize_suite(
        db, manager, get_suite(db, manager.organization_id, suite_id),
        payload.confirm_finalize, payload.note)


@router.post("/suites/{suite_id}/reviews", response_model=AIEvaluationSuiteResponse)
def evaluation_review(suite_id: UUID, payload: AIEvaluationReviewWrite,
                      manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_review(
        db, manager, get_suite(db, manager.organization_id, suite_id),
        payload.review_role, payload.action, payload.evidence_reference, payload.note)


@router.post("/suites/{suite_id}/decision", response_model=AIEvaluationSuiteResponse)
def evaluation_decision(suite_id: UUID, payload: AIEvaluationDecision,
                        admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return decide_promotion(
        db, admin, get_suite(db, admin.organization_id, suite_id),
        payload.outcome, payload.confirm_decision, payload.note)


@router.post("/suites/{suite_id}/revoke", response_model=AIEvaluationSuiteResponse)
def evaluation_revoke(suite_id: UUID, payload: AIEvaluationRevoke,
                      manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return revoke_promotion(
        db, manager, get_suite(db, manager.organization_id, suite_id),
        payload.confirm_revoke, payload.note)

