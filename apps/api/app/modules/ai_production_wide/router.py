from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_production_wide.models import AIProductionDecisionLog
from app.modules.ai_production_wide.schemas import (
    AIProductionDecisionLogReview,
    AIProductionWideApprovalWrite,
    AIProductionWideCreate,
    AIProductionWideDashboard,
    AIProductionWideDecision,
    AIProductionWideIncidentCreate,
    AIProductionWideIncidentResolve,
    AIProductionWideLifecycle,
    AIProductionWideMonitorCreate,
    AIProductionWideResponse,
)
from app.modules.ai_production_wide.service import (
    create_authorization,
    create_monitor,
    decide_authorization,
    get_authorization,
    list_authorizations,
    record_approval,
    report_incident,
    resolve_incident,
    review_decision_log,
    revoke_authorization,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-production-wide", tags=["ai-production-wide"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AIProductionWideDashboard)
def dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return {"authorizations": list_authorizations(db, current_user.organization_id)}


@router.post("/authorizations", response_model=AIProductionWideResponse, status_code=201)
def authorization_create(payload: AIProductionWideCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return create_authorization(db, manager, payload)


@router.post("/authorizations/{authorization_id}/approvals", response_model=AIProductionWideResponse)
def authorization_approval(authorization_id: UUID, payload: AIProductionWideApprovalWrite, manager: Manager,
                           db: Annotated[Session, Depends(get_db)]):
    return record_approval(db, manager, get_authorization(db, manager.organization_id, authorization_id),
                           payload.approval_role, payload.action, payload.evidence_reference, payload.note)


@router.post("/authorizations/{authorization_id}/decision", response_model=AIProductionWideResponse)
def authorization_decision(authorization_id: UUID, payload: AIProductionWideDecision, admin: Admin,
                           db: Annotated[Session, Depends(get_db)]):
    return decide_authorization(db, admin, get_authorization(db, admin.organization_id, authorization_id),
                                payload.outcome, payload.confirm_decision, payload.note)


@router.post("/decision-logs/{log_id}/review")
def decision_log_review(log_id: UUID, payload: AIProductionDecisionLogReview, manager: Manager,
                        db: Annotated[Session, Depends(get_db)]):
    log = db.scalar(select(AIProductionDecisionLog).where(
        AIProductionDecisionLog.id == log_id,
        AIProductionDecisionLog.organization_id == manager.organization_id,
    ))
    if log is None:
        from fastapi import HTTPException
        raise HTTPException(404, "AI Decision Log entry not found")
    return review_decision_log(db, manager, log, **payload.model_dump())


@router.post("/authorizations/{authorization_id}/monitors", response_model=AIProductionWideResponse)
def authorization_monitor(authorization_id: UUID, payload: AIProductionWideMonitorCreate, manager: Manager,
                          db: Annotated[Session, Depends(get_db)]):
    return create_monitor(db, manager, get_authorization(db, manager.organization_id, authorization_id),
                          monitor_key=payload.monitor_key, note=payload.note, confirm=payload.confirm_monitor_snapshot)


@router.post("/authorizations/{authorization_id}/incidents", response_model=AIProductionWideResponse)
def authorization_incident(authorization_id: UUID, payload: AIProductionWideIncidentCreate, manager: Manager,
                           db: Annotated[Session, Depends(get_db)]):
    return report_incident(db, manager, get_authorization(db, manager.organization_id, authorization_id), **payload.model_dump())


@router.post("/authorizations/{authorization_id}/incidents/{incident_id}/resolve", response_model=AIProductionWideResponse)
def authorization_incident_resolve(authorization_id: UUID, incident_id: UUID, payload: AIProductionWideIncidentResolve,
                                   manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return resolve_incident(db, manager, get_authorization(db, manager.organization_id, authorization_id), incident_id,
                            resolution_reference=payload.resolution_reference, resolution_note=payload.resolution_note,
                            confirm=payload.confirm_resolution)


@router.post("/authorizations/{authorization_id}/revoke", response_model=AIProductionWideResponse)
def authorization_revoke(authorization_id: UUID, payload: AIProductionWideLifecycle, admin: Admin,
                         db: Annotated[Session, Depends(get_db)]):
    return revoke_authorization(db, admin, get_authorization(db, admin.organization_id, authorization_id),
                                confirm=payload.confirm, note=payload.note)
