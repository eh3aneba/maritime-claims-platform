from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_private_pilot.schemas import (
    AIPrivatePilotApprovalWrite,
    AIPrivatePilotComplete,
    AIPrivatePilotCreate,
    AIPrivatePilotDashboard,
    AIPrivatePilotDecision,
    AIPrivatePilotDocumentCreate,
    AIPrivatePilotIncidentCreate,
    AIPrivatePilotIncidentResolve,
    AIPrivatePilotResponse,
    AIPrivatePilotRevoke,
    AIPrivatePilotRunOutcome,
)
from app.modules.ai_private_pilot.service import (
    attest_document,
    complete_pilot,
    create_pilot,
    decide_pilot,
    get_pilot,
    get_run,
    list_pilots,
    record_approval,
    record_run_outcome,
    report_incident,
    resolve_incident,
    revoke_document,
    revoke_pilot,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-private-pilot", tags=["ai-private-pilot"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AIPrivatePilotDashboard)
def dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return AIPrivatePilotDashboard(pilots=list_pilots(db, current_user.organization_id))


@router.post("/pilots", response_model=AIPrivatePilotResponse, status_code=201)
def pilot_create(payload: AIPrivatePilotCreate, manager: Manager,
                 db: Annotated[Session, Depends(get_db)]):
    return create_pilot(db, manager, payload)


@router.post("/pilots/{pilot_id}/approvals", response_model=AIPrivatePilotResponse)
def pilot_approval(pilot_id: UUID, payload: AIPrivatePilotApprovalWrite,
                   manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_approval(
        db, manager, get_pilot(db, manager.organization_id, pilot_id),
        payload.approval_role, payload.action, payload.evidence_reference, payload.note)


@router.post("/pilots/{pilot_id}/decision", response_model=AIPrivatePilotResponse)
def pilot_decision(pilot_id: UUID, payload: AIPrivatePilotDecision,
                   admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return decide_pilot(
        db, admin, get_pilot(db, admin.organization_id, pilot_id),
        payload.outcome, payload.confirm_decision, payload.note)


@router.post("/pilots/{pilot_id}/documents", response_model=AIPrivatePilotResponse,
             status_code=201)
def pilot_document(pilot_id: UUID, payload: AIPrivatePilotDocumentCreate,
                   manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return attest_document(
        db, manager, get_pilot(db, manager.organization_id, pilot_id), payload)


@router.post("/pilots/{pilot_id}/documents/{eligibility_id}/revoke",
             response_model=AIPrivatePilotResponse)
def pilot_document_revoke(pilot_id: UUID, eligibility_id: UUID,
                          payload: AIPrivatePilotRevoke, manager: Manager,
                          db: Annotated[Session, Depends(get_db)]):
    return revoke_document(
        db, manager, get_pilot(db, manager.organization_id, pilot_id), eligibility_id,
        payload.confirm_revoke, payload.note)


@router.post("/runs/{run_id}/outcome", response_model=AIPrivatePilotResponse)
def pilot_run_outcome(run_id: UUID, payload: AIPrivatePilotRunOutcome,
                      current_user: CurrentUser,
                      db: Annotated[Session, Depends(get_db)]):
    return record_run_outcome(
        db, current_user, get_run(db, current_user.organization_id, run_id),
        human_review_action=payload.human_review_action,
        output_candidate_count=payload.output_candidate_count,
        human_edit_count=payload.human_edit_count, latency_ms=payload.latency_ms,
        observed_provider_cost_microusd=payload.observed_provider_cost_microusd,
        evidence_reference=payload.evidence_reference, note=payload.note,
        confirm_human_review=payload.confirm_human_review)


@router.post("/pilots/{pilot_id}/incidents", response_model=AIPrivatePilotResponse,
             status_code=201)
def pilot_incident(pilot_id: UUID, payload: AIPrivatePilotIncidentCreate,
                   manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return report_incident(
        db, manager, get_pilot(db, manager.organization_id, pilot_id),
        severity=payload.severity, category=payload.category,
        evidence_reference=payload.evidence_reference, note=payload.note,
        confirm_pause=payload.confirm_pause)


@router.post("/pilots/{pilot_id}/incidents/{incident_id}/resolve",
             response_model=AIPrivatePilotResponse)
def pilot_incident_resolve(pilot_id: UUID, incident_id: UUID,
                           payload: AIPrivatePilotIncidentResolve, admin: Admin,
                           db: Annotated[Session, Depends(get_db)]):
    return resolve_incident(
        db, admin, get_pilot(db, admin.organization_id, pilot_id), incident_id,
        resolution_reference=payload.resolution_reference,
        resolution_note=payload.resolution_note, resume_pilot=payload.resume_pilot,
        confirm_resolution=payload.confirm_resolution)


@router.post("/pilots/{pilot_id}/revoke", response_model=AIPrivatePilotResponse)
def pilot_revoke(pilot_id: UUID, payload: AIPrivatePilotRevoke,
                 manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return revoke_pilot(
        db, manager, get_pilot(db, manager.organization_id, pilot_id),
        payload.confirm_revoke, payload.note)


@router.post("/pilots/{pilot_id}/complete", response_model=AIPrivatePilotResponse)
def pilot_complete(pilot_id: UUID, payload: AIPrivatePilotComplete,
                   admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return complete_pilot(
        db, admin, get_pilot(db, admin.organization_id, pilot_id),
        payload.confirm_complete, payload.note)
