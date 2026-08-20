from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.pilot_operations.schemas import (
    ExitManifestCreate, ExitManifestResponse, GovernanceApproval, GovernanceProfileResponse,
    GovernanceProfileWrite, IncidentCreate, IncidentResponse, IncidentTransition,
    MonitorRunCreate, MonitorRunResponse, PilotOperationsDashboard, ReadinessAttest,
    ReadinessCreate, ReadinessResponse, RehearsalComplete, RehearsalCreate,
    RehearsalEvidenceWrite, RehearsalFindingCreate, RehearsalFindingTransition, RehearsalResponse,
)
from app.modules.pilot_operations.service import (
    approve_governance, attest_readiness, create_exit_manifest, create_incident, create_readiness,
    complete_rehearsal, create_rehearsal, create_rehearsal_finding, dashboard, get_governance,
    get_incident, get_readiness, get_rehearsal, get_rehearsal_finding, run_monitor,
    start_rehearsal, transition_incident, transition_rehearsal_finding, write_governance,
    write_rehearsal_evidence,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/pilot-operations", tags=["pilot-operations"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]


@router.get("", response_model=PilotOperationsDashboard)
def operations_dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    readiness, monitors, incidents, profile, exits, rehearsals = dashboard(db, current_user.organization_id)
    return PilotOperationsDashboard(readiness_reviews=readiness, monitor_runs=monitors,
                                    incidents=incidents, governance_profile=profile,
                                    exit_manifests=exits, rehearsals=rehearsals)


@router.post("/readiness", response_model=ReadinessResponse, status_code=201)
def readiness_create(payload: ReadinessCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return create_readiness(db, current_user, payload)


@router.post("/readiness/{item_id}/attest", response_model=ReadinessResponse)
def readiness_attest(item_id: UUID, payload: ReadinessAttest, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return attest_readiness(db, manager, get_readiness(db, manager.organization_id, item_id), payload.confirm_ready, payload.note)


@router.post("/monitor-runs", response_model=MonitorRunResponse, status_code=201)
def monitor_run(payload: MonitorRunCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return run_monitor(db, manager, payload)


@router.post("/incidents", response_model=IncidentResponse, status_code=201)
def incident_create(payload: IncidentCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return create_incident(db, manager, payload)


@router.post("/incidents/{item_id}/transition", response_model=IncidentResponse)
def incident_transition(item_id: UUID, payload: IncidentTransition, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return transition_incident(db, manager, get_incident(db, manager.organization_id, item_id), payload.action, payload.note)


@router.put("/governance", response_model=GovernanceProfileResponse)
def governance_write(payload: GovernanceProfileWrite, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return write_governance(db, manager, payload)


@router.post("/governance/approve", response_model=GovernanceProfileResponse)
def governance_approve(payload: GovernanceApproval, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return approve_governance(db, manager, get_governance(db, manager.organization_id), payload.confirm_approved, payload.note)


@router.post("/claims/{claim_id}/exit-manifests", response_model=ExitManifestResponse, status_code=201)
def exit_manifest(claim_id: UUID, payload: ExitManifestCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return create_exit_manifest(db, manager, claim_id, payload.idempotency_key, payload.confirm_manifest_only)


@router.post("/rehearsals", response_model=RehearsalResponse, status_code=201)
def rehearsal_create(payload: RehearsalCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return create_rehearsal(db, current_user, payload)


@router.post("/rehearsals/{item_id}/start", response_model=RehearsalResponse)
def rehearsal_start(item_id: UUID, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return start_rehearsal(db, manager, get_rehearsal(db, manager.organization_id, item_id))


@router.put("/rehearsals/{item_id}/evidence", response_model=RehearsalResponse)
def rehearsal_evidence(item_id: UUID, payload: RehearsalEvidenceWrite, current_user: CurrentUser,
                       db: Annotated[Session, Depends(get_db)]):
    return write_rehearsal_evidence(db, current_user,
                                    get_rehearsal(db, current_user.organization_id, item_id), payload)


@router.post("/rehearsals/{item_id}/findings", response_model=RehearsalResponse, status_code=201)
def rehearsal_finding_create(item_id: UUID, payload: RehearsalFindingCreate, current_user: CurrentUser,
                             db: Annotated[Session, Depends(get_db)]):
    return create_rehearsal_finding(db, current_user,
                                    get_rehearsal(db, current_user.organization_id, item_id), payload)


@router.post("/rehearsals/{item_id}/findings/{finding_id}/transition", response_model=RehearsalResponse)
def rehearsal_finding_transition(item_id: UUID, finding_id: UUID, payload: RehearsalFindingTransition,
                                 current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return transition_rehearsal_finding(
        db, current_user, get_rehearsal(db, current_user.organization_id, item_id),
        get_rehearsal_finding(db, current_user.organization_id, finding_id), payload.action, payload.note,
    )


@router.post("/rehearsals/{item_id}/complete", response_model=RehearsalResponse)
def rehearsal_complete(item_id: UUID, payload: RehearsalComplete, manager: Manager,
                       db: Annotated[Session, Depends(get_db)]):
    return complete_rehearsal(db, manager, get_rehearsal(db, manager.organization_id, item_id),
                              payload.outcome, payload.confirm_decision, payload.note)
