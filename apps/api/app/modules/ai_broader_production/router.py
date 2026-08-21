from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_broader_production.schemas import (
    AIBroaderProductionApprovalWrite,
    AIBroaderProductionCreate,
    AIBroaderProductionDashboard,
    AIBroaderProductionDecision,
    AIBroaderProductionDocumentCreate,
    AIBroaderProductionIncidentCreate,
    AIBroaderProductionIncidentResolve,
    AIBroaderProductionLifecycle,
    AIBroaderProductionMonitorCreate,
    AIBroaderProductionResponse,
    AIBroaderProductionRunOutcome,
)
from app.modules.ai_broader_production.service import (
    attest_document,
    complete_authorization,
    create_authorization,
    decide_authorization,
    get_authorization,
    get_run,
    list_authorizations,
    record_approval,
    record_monitor,
    record_run_outcome,
    report_incident,
    resolve_incident,
    resume_authorization,
    revoke_authorization,
    revoke_document,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-broader-production", tags=["ai-broader-production"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AIBroaderProductionDashboard)
def dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return AIBroaderProductionDashboard(authorizations=list_authorizations(db, current_user.organization_id))


@router.post("/authorizations", response_model=AIBroaderProductionResponse, status_code=201)
def authorization_create(payload: AIBroaderProductionCreate, manager: Manager,
                         db: Annotated[Session, Depends(get_db)]):
    return create_authorization(db, manager, payload)


@router.post("/authorizations/{authorization_id}/approvals", response_model=AIBroaderProductionResponse)
def authorization_approval(authorization_id: UUID, payload: AIBroaderProductionApprovalWrite,
                           manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_approval(
        db, manager, get_authorization(db, manager.organization_id, authorization_id),
        payload.approval_role, payload.action, payload.evidence_reference, payload.note,
    )


@router.post("/authorizations/{authorization_id}/decision", response_model=AIBroaderProductionResponse)
def authorization_decision(authorization_id: UUID, payload: AIBroaderProductionDecision,
                           admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return decide_authorization(
        db, admin, get_authorization(db, admin.organization_id, authorization_id),
        payload.outcome, payload.confirm_decision, payload.note,
    )


@router.post("/authorizations/{authorization_id}/documents", response_model=AIBroaderProductionResponse, status_code=201)
def authorization_document(authorization_id: UUID, payload: AIBroaderProductionDocumentCreate,
                           manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return attest_document(
        db, manager, get_authorization(db, manager.organization_id, authorization_id), payload,
    )


@router.post("/authorizations/{authorization_id}/documents/{eligibility_id}/revoke", response_model=AIBroaderProductionResponse)
def authorization_document_revoke(authorization_id: UUID, eligibility_id: UUID,
                                  payload: AIBroaderProductionLifecycle,
                                  manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return revoke_document(
        db, manager, get_authorization(db, manager.organization_id, authorization_id),
        eligibility_id, payload.confirm, payload.note,
    )


@router.post("/runs/{run_id}/outcome", response_model=AIBroaderProductionResponse)
def run_outcome(run_id: UUID, payload: AIBroaderProductionRunOutcome,
                current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return record_run_outcome(
        db, current_user, get_run(db, current_user.organization_id, run_id),
        human_review_action=payload.human_review_action,
        output_candidate_count=payload.output_candidate_count,
        human_edit_count=payload.human_edit_count,
        unsupported_output_count=payload.unsupported_output_count,
        source_grounded_output_count=payload.source_grounded_output_count,
        source_grounding_total_count=payload.source_grounding_total_count,
        latency_ms=payload.latency_ms,
        observed_provider_cost_microusd=payload.observed_provider_cost_microusd,
        evidence_reference=payload.evidence_reference,
        note=payload.note,
        confirm_human_review=payload.confirm_human_review,
    )


@router.post("/authorizations/{authorization_id}/monitors", response_model=AIBroaderProductionResponse, status_code=201)
def authorization_monitor(authorization_id: UUID, payload: AIBroaderProductionMonitorCreate,
                          manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_monitor(
        db, manager, get_authorization(db, manager.organization_id, authorization_id),
        payload.monitor_key, payload.note, payload.confirm_live_monitor_snapshot,
    )


@router.post("/authorizations/{authorization_id}/incidents", response_model=AIBroaderProductionResponse, status_code=201)
def authorization_incident(authorization_id: UUID, payload: AIBroaderProductionIncidentCreate,
                           manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return report_incident(
        db, manager, get_authorization(db, manager.organization_id, authorization_id),
        severity=payload.severity, category=payload.category,
        evidence_reference=payload.evidence_reference, note=payload.note,
        confirm=payload.confirm_pause_and_rollback,
    )


@router.post("/authorizations/{authorization_id}/incidents/{incident_id}/resolve", response_model=AIBroaderProductionResponse)
def authorization_incident_resolve(authorization_id: UUID, incident_id: UUID,
                                   payload: AIBroaderProductionIncidentResolve, admin: Admin,
                                   db: Annotated[Session, Depends(get_db)]):
    return resolve_incident(
        db, admin, get_authorization(db, admin.organization_id, authorization_id), incident_id,
        resolution_reference=payload.resolution_reference,
        resolution_note=payload.resolution_note,
        confirm=payload.confirm_resolution,
    )


@router.post("/authorizations/{authorization_id}/resume", response_model=AIBroaderProductionResponse)
def authorization_resume(authorization_id: UUID, payload: AIBroaderProductionLifecycle,
                         admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return resume_authorization(
        db, admin, get_authorization(db, admin.organization_id, authorization_id),
        payload.confirm, payload.note,
    )


@router.post("/authorizations/{authorization_id}/revoke", response_model=AIBroaderProductionResponse)
def authorization_revoke(authorization_id: UUID, payload: AIBroaderProductionLifecycle,
                         manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return revoke_authorization(
        db, manager, get_authorization(db, manager.organization_id, authorization_id),
        payload.confirm, payload.note,
    )


@router.post("/authorizations/{authorization_id}/complete", response_model=AIBroaderProductionResponse)
def authorization_complete(authorization_id: UUID, payload: AIBroaderProductionLifecycle,
                           admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return complete_authorization(
        db, admin, get_authorization(db, admin.organization_id, authorization_id),
        payload.confirm, payload.note,
    )
