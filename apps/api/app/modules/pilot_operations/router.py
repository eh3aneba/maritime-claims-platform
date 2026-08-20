from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.pilot_operations.schemas import (
    ArchitectureBaselineAttest, ArchitectureBaselineCreate, ArchitectureBaselineResponse,
    ArchitectureControlWrite, ControlVerificationGateComplete, ControlVerificationGateCreate,
    ControlVerificationGateResponse, ExitManifestCreate, ExitManifestResponse, GovernanceApproval,
    GovernanceProfileResponse, GovernanceProfileWrite, IncidentCreate, IncidentResponse,
    IncidentTransition, MonitorRunCreate, MonitorRunResponse, PilotCaseRunWrite,
    OperationalAcceptanceApprovalWrite, OperationalAcceptanceCreate,
    OperationalAcceptanceDecision, OperationalAcceptanceResponse,
    PilotExecutionComplete, PilotExecutionCreate, PilotExecutionResponse, PilotOperationsDashboard,
    ProductGapCreate, ProductGapTransition, ProductionControlEvidenceReview,
    ProductionControlEvidenceSubmit, ReadinessAttest, ReadinessCreate, ReadinessResponse,
    RehearsalComplete, RehearsalCreate,
    RehearsalEvidenceWrite, RehearsalFindingCreate, RehearsalFindingTransition, RehearsalResponse,
)
from app.modules.pilot_operations.service import (
    approve_governance, attest_architecture_baseline, attest_readiness,
    complete_control_verification_gate, complete_pilot_execution, complete_rehearsal,
    create_architecture_baseline, create_control_verification_gate,
    create_exit_manifest, create_incident, create_pilot_execution, create_product_gap,
    create_operational_acceptance, decide_operational_acceptance,
    create_readiness, create_rehearsal, create_rehearsal_finding, dashboard,
    get_architecture_baseline, get_control_verification_gate, get_governance, get_incident,
    get_operational_acceptance,
    get_pilot_execution, get_product_gap, get_production_control_evidence, get_readiness,
    get_rehearsal, get_rehearsal_finding, review_production_control_evidence, run_monitor,
    record_operational_acceptance_approval,
    start_pilot_execution, start_rehearsal, transition_incident, transition_product_gap,
    submit_production_control_evidence, transition_rehearsal_finding,
    write_architecture_control, write_governance,
    write_pilot_case_run, write_rehearsal_evidence,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/pilot-operations", tags=["pilot-operations"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=PilotOperationsDashboard)
def operations_dashboard(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    (readiness, monitors, incidents, profile, exits, rehearsals, executions, baselines, gates,
     acceptances) = dashboard(db, current_user.organization_id)
    return PilotOperationsDashboard(readiness_reviews=readiness, monitor_runs=monitors,
                                    incidents=incidents, governance_profile=profile,
                                    exit_manifests=exits, rehearsals=rehearsals,
                                    pilot_executions=executions, architecture_baselines=baselines,
                                    control_verification_gates=gates,
                                    operational_acceptances=acceptances)


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


@router.post("/pilot-executions", response_model=PilotExecutionResponse, status_code=201)
def pilot_execution_create(payload: PilotExecutionCreate, current_user: CurrentUser,
                           db: Annotated[Session, Depends(get_db)]):
    return create_pilot_execution(db, current_user, payload)


@router.post("/pilot-executions/{item_id}/start", response_model=PilotExecutionResponse)
def pilot_execution_start(item_id: UUID, manager: Manager,
                          db: Annotated[Session, Depends(get_db)]):
    return start_pilot_execution(
        db, manager, get_pilot_execution(db, manager.organization_id, item_id))


@router.put("/pilot-executions/{item_id}/case-runs", response_model=PilotExecutionResponse)
def pilot_case_run_write(item_id: UUID, payload: PilotCaseRunWrite, current_user: CurrentUser,
                         db: Annotated[Session, Depends(get_db)]):
    return write_pilot_case_run(
        db, current_user, get_pilot_execution(db, current_user.organization_id, item_id), payload)


@router.post("/pilot-executions/{item_id}/gaps", response_model=PilotExecutionResponse,
             status_code=201)
def product_gap_create(item_id: UUID, payload: ProductGapCreate, current_user: CurrentUser,
                       db: Annotated[Session, Depends(get_db)]):
    return create_product_gap(
        db, current_user, get_pilot_execution(db, current_user.organization_id, item_id), payload)


@router.post("/pilot-executions/{item_id}/gaps/{gap_id}/transition",
             response_model=PilotExecutionResponse)
def product_gap_transition(item_id: UUID, gap_id: UUID, payload: ProductGapTransition,
                           current_user: CurrentUser,
                           db: Annotated[Session, Depends(get_db)]):
    return transition_product_gap(
        db, current_user, get_pilot_execution(db, current_user.organization_id, item_id),
        get_product_gap(db, current_user.organization_id, gap_id), payload.action, payload.note)


@router.post("/pilot-executions/{item_id}/complete", response_model=PilotExecutionResponse)
def pilot_execution_complete(item_id: UUID, payload: PilotExecutionComplete, manager: Manager,
                             db: Annotated[Session, Depends(get_db)]):
    return complete_pilot_execution(
        db, manager, get_pilot_execution(db, manager.organization_id, item_id),
        payload.outcome, payload.confirm_outcome, payload.note)


@router.post("/architecture-baselines", response_model=ArchitectureBaselineResponse,
             status_code=201)
def architecture_baseline_create(payload: ArchitectureBaselineCreate, manager: Manager,
                                 db: Annotated[Session, Depends(get_db)]):
    return create_architecture_baseline(db, manager, payload)


@router.put("/architecture-baselines/{item_id}/controls",
            response_model=ArchitectureBaselineResponse)
def architecture_control_write(item_id: UUID, payload: ArchitectureControlWrite,
                               manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return write_architecture_control(
        db, manager, get_architecture_baseline(db, manager.organization_id, item_id), payload)


@router.post("/architecture-baselines/{item_id}/attest",
             response_model=ArchitectureBaselineResponse)
def architecture_baseline_attest(item_id: UUID, payload: ArchitectureBaselineAttest,
                                 manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return attest_architecture_baseline(
        db, manager, get_architecture_baseline(db, manager.organization_id, item_id),
        payload.confirm_reviewed, payload.note)


@router.post("/control-verification-gates", response_model=ControlVerificationGateResponse,
             status_code=201)
def control_verification_gate_create(payload: ControlVerificationGateCreate, manager: Manager,
                                     db: Annotated[Session, Depends(get_db)]):
    return create_control_verification_gate(db, manager, payload)


@router.post("/control-verification-gates/{item_id}/evidence",
             response_model=ControlVerificationGateResponse, status_code=201)
def production_control_evidence_submit(item_id: UUID, payload: ProductionControlEvidenceSubmit,
                                       manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return submit_production_control_evidence(
        db, manager, get_control_verification_gate(db, manager.organization_id, item_id), payload)


@router.post("/control-verification-gates/{item_id}/evidence/{evidence_id}/review",
             response_model=ControlVerificationGateResponse)
def production_control_evidence_review(item_id: UUID, evidence_id: UUID,
                                       payload: ProductionControlEvidenceReview,
                                       manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return review_production_control_evidence(
        db, manager, get_control_verification_gate(db, manager.organization_id, item_id),
        get_production_control_evidence(db, manager.organization_id, evidence_id),
        payload.action, payload.review_reference, payload.note)


@router.post("/control-verification-gates/{item_id}/complete",
             response_model=ControlVerificationGateResponse)
def control_verification_gate_complete(item_id: UUID, payload: ControlVerificationGateComplete,
                                       manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return complete_control_verification_gate(
        db, manager, get_control_verification_gate(db, manager.organization_id, item_id),
        payload.confirm_verified, payload.note)


@router.post("/operational-acceptances", response_model=OperationalAcceptanceResponse,
             status_code=201)
def operational_acceptance_create(payload: OperationalAcceptanceCreate, manager: Manager,
                                  db: Annotated[Session, Depends(get_db)]):
    return create_operational_acceptance(db, manager, payload)


@router.post("/operational-acceptances/{item_id}/approvals",
             response_model=OperationalAcceptanceResponse)
def operational_acceptance_approval(item_id: UUID,
                                    payload: OperationalAcceptanceApprovalWrite,
                                    manager: Manager,
                                    db: Annotated[Session, Depends(get_db)]):
    return record_operational_acceptance_approval(
        db, manager, get_operational_acceptance(db, manager.organization_id, item_id),
        payload.approval_role, payload.action, payload.evidence_reference, payload.note)


@router.post("/operational-acceptances/{item_id}/decision",
             response_model=OperationalAcceptanceResponse)
def operational_acceptance_decision(item_id: UUID, payload: OperationalAcceptanceDecision,
                                    admin: Admin,
                                    db: Annotated[Session, Depends(get_db)]):
    return decide_operational_acceptance(
        db, admin, get_operational_acceptance(db, admin.organization_id, item_id),
        payload.outcome, payload.confirm_decision, payload.note)
