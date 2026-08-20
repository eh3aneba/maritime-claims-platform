import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.correspondence.models import ClaimCorrespondence
from app.modules.documents.models import Document
from app.modules.email_ingestion.models import EmailAdapterRun, EmailMessageStatus, EmailRetentionRun, IngestedEmailMessage
from app.modules.external_portal.models import ExternalPortalInvitation, ExternalPortalSession, ExternalPortalSubmission
from app.modules.pilot_operations.models import (
    DeploymentReadinessReview, DesignPartnerRehearsal, OperationalIncident, OperationalMonitorRun,
    PilotExitManifest, PilotGovernanceProfile, PrivatePilotCaseRun, PrivatePilotExecution,
    ProductGapFinding, ProductionArchitectureBaseline, ProductionArchitectureControl,
    ProductionControlEvidence, ProductionControlVerificationGate,
    RehearsalControlEvidence, RehearsalRemediationFinding,
)
from app.modules.pilot_operations.schemas import (
    ArchitectureBaselineCreate, ArchitectureControlWrite, ControlVerificationGateCreate,
    GovernanceProfileWrite, IncidentCreate, MonitorRunCreate, PilotCaseRunWrite,
    PilotExecutionCreate, ProductGapCreate, ProductionControlEvidenceSubmit, ReadinessCreate,
    RehearsalCreate, RehearsalEvidenceWrite, RehearsalFindingCreate,
)
from app.modules.users.models import User

READINESS_CONTROLS = {"tls", "secret_references", "backup_restore", "migrations", "malware_scan",
                      "least_privilege", "retention", "incident_contacts"}
ARCHITECTURE_CONTROLS = {"identity_access", "application_security", "evidence_storage",
                         "observability", "backup_dr", "data_governance", "deployment_iac",
                         "interoperability", "ai_governance"}
FOUNDATIONAL_PRODUCTION_CONTROLS = {"identity_access", "evidence_storage", "observability",
                                   "backup_dr", "deployment_iac"}
CONTROL_VERIFICATION_PROFILES = {
    "foundational_v1": FOUNDATIONAL_PRODUCTION_CONTROLS,
    "architecture_v2": ARCHITECTURE_CONTROLS,
}
LATEST_CONTROL_VERIFICATION_PROFILE = "architecture_v2"
EVIDENCE_REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")


def _audit(db: Session, user: User, action: str, kind: str, entity: UUID, values: dict, details: str) -> None:
    write_audit_log(db, organization_id=user.organization_id, user_id=user.id, action=action,
                    entity_type=kind, entity_id=entity, new_values=values, details=details)


def dashboard(db: Session, organization_id: UUID):
    readiness = list(db.scalars(select(DeploymentReadinessReview).where(
        DeploymentReadinessReview.organization_id == organization_id).order_by(DeploymentReadinessReview.created_at.desc())))
    monitors = list(db.scalars(select(OperationalMonitorRun).where(
        OperationalMonitorRun.organization_id == organization_id).order_by(OperationalMonitorRun.run_at.desc()).limit(25)))
    incidents = list(db.scalars(select(OperationalIncident).where(
        OperationalIncident.organization_id == organization_id).order_by(OperationalIncident.created_at.desc())))
    profile = db.scalar(select(PilotGovernanceProfile).where(PilotGovernanceProfile.organization_id == organization_id))
    exits = list(db.scalars(select(PilotExitManifest).where(
        PilotExitManifest.organization_id == organization_id).order_by(PilotExitManifest.created_at.desc()).limit(25)))
    rehearsals = list_rehearsals(db, organization_id)
    executions = list_pilot_executions(db, organization_id)
    baselines = list_architecture_baselines(db, organization_id)
    verification_gates = list_control_verification_gates(db, organization_id)
    return readiness, monitors, incidents, profile, exits, rehearsals, executions, baselines, verification_gates


def create_readiness(db: Session, user: User, payload: ReadinessCreate) -> DeploymentReadinessReview:
    if set(payload.controls) != READINESS_CONTROLS:
        raise HTTPException(422, "Readiness review must contain exactly the eight required controls")
    canonical = json.dumps(payload.controls, sort_keys=True, separators=(",", ":"))
    item = DeploymentReadinessReview(
        organization_id=user.organization_id, created_by_id=user.id, environment=payload.environment,
        review_key=payload.review_key, controls=payload.controls,
        status="draft" if all(payload.controls.values()) else "blocked",
        snapshot_hash=sha256(canonical.encode()).hexdigest(),
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This environment review key already exists") from exc
    _audit(db, user, "CREATE_DEPLOYMENT_READINESS_REVIEW", "deployment_readiness_review", item.id,
           {"environment": item.environment, "status": item.status, "snapshot_hash": item.snapshot_hash},
           "Boolean control snapshot only; no infrastructure secret values stored.")
    db.commit(); db.refresh(item); return item


def get_readiness(db: Session, org: UUID, item_id: UUID) -> DeploymentReadinessReview:
    item = db.scalar(select(DeploymentReadinessReview).where(
        DeploymentReadinessReview.id == item_id, DeploymentReadinessReview.organization_id == org))
    if item is None: raise HTTPException(404, "Readiness review not found")
    return item


def attest_readiness(db: Session, user: User, item: DeploymentReadinessReview,
                     confirm: bool, note: str) -> DeploymentReadinessReview:
    if not confirm: raise HTTPException(422, "Explicit readiness confirmation is required")
    if set(item.controls) != READINESS_CONTROLS or not all(item.controls.values()):
        raise HTTPException(409, "All required controls must pass before readiness attestation")
    item.status = "ready"; item.attested_by_id = user.id; item.attestation_note = note.strip(); item.attested_at = datetime.now(UTC)
    _audit(db, user, "ATTEST_DEPLOYMENT_READY", "deployment_readiness_review", item.id,
           {"status": item.status, "snapshot_hash": item.snapshot_hash}, item.attestation_note)
    db.commit(); db.refresh(item); return item


def run_monitor(db: Session, user: User, payload: MonitorRunCreate) -> OperationalMonitorRun:
    existing = db.scalar(select(OperationalMonitorRun).where(
        OperationalMonitorRun.organization_id == user.organization_id,
        OperationalMonitorRun.idempotency_key == payload.idempotency_key))
    if existing is not None: return existing
    now = datetime.now(UTC)
    metrics = {
        "failed_adapter_runs": db.scalar(select(func.count()).select_from(EmailAdapterRun).where(EmailAdapterRun.organization_id == user.organization_id, EmailAdapterRun.status == "failed")) or 0,
        "pending_email_intake": db.scalar(select(func.count()).select_from(IngestedEmailMessage).where(IngestedEmailMessage.organization_id == user.organization_id, IngestedEmailMessage.status == EmailMessageStatus.PENDING_REVIEW)) or 0,
        "expired_or_revoked_portal_sessions": db.scalar(select(func.count()).select_from(ExternalPortalSession).join(ExternalPortalInvitation, ExternalPortalInvitation.id == ExternalPortalSession.invitation_id).where(ExternalPortalSession.organization_id == user.organization_id, (ExternalPortalSession.expires_at <= now) | (ExternalPortalSession.revoked_at.is_not(None)))) or 0,
        "retention_runs": db.scalar(select(func.count()).select_from(EmailRetentionRun).where(EmailRetentionRun.organization_id == user.organization_id)) or 0,
    }
    alerts = []
    for key, threshold in [("failed_adapter_runs", payload.adapter_failure_threshold),
                           ("pending_email_intake", payload.pending_intake_threshold),
                           ("expired_or_revoked_portal_sessions", payload.expired_portal_threshold)]:
        if metrics[key] >= threshold: alerts.append({"metric": key, "value": metrics[key], "threshold": threshold})
    item = OperationalMonitorRun(organization_id=user.organization_id, initiated_by_id=user.id,
                                 idempotency_key=payload.idempotency_key, metrics=metrics, alerts=alerts,
                                 status="attention_required" if alerts else "healthy", run_at=now)
    db.add(item); db.flush()
    _audit(db, user, "RUN_OPERATIONAL_MONITOR", "operational_monitor_run", item.id,
           {"status": item.status, "metrics": metrics, "alert_count": len(alerts)},
           "Telemetry contains counts and statuses only; no claim content, tokens or credentials.")
    db.commit(); db.refresh(item); return item


def create_incident(db: Session, user: User, payload: IncidentCreate) -> OperationalIncident:
    if payload.monitor_run_id:
        run = db.scalar(select(OperationalMonitorRun).where(OperationalMonitorRun.id == payload.monitor_run_id,
                        OperationalMonitorRun.organization_id == user.organization_id))
        if run is None: raise HTTPException(404, "Monitor run not found")
    item = OperationalIncident(organization_id=user.organization_id, monitor_run_id=payload.monitor_run_id,
        created_by_id=user.id, updated_by_id=user.id, severity=payload.severity, category=payload.category,
        title=payload.title.strip(), summary=payload.summary.strip(), owner_label=payload.owner_label.strip(), status="open")
    db.add(item); db.flush()
    _audit(db, user, "OPEN_OPERATIONAL_INCIDENT", "operational_incident", item.id,
           {"severity": item.severity, "category": item.category, "status": item.status}, item.summary)
    db.commit(); db.refresh(item); return item


def get_incident(db: Session, org: UUID, item_id: UUID) -> OperationalIncident:
    item = db.scalar(select(OperationalIncident).where(OperationalIncident.id == item_id,
                     OperationalIncident.organization_id == org))
    if item is None: raise HTTPException(404, "Operational incident not found")
    return item


def transition_incident(db: Session, user: User, item: OperationalIncident, action: str, note: str) -> OperationalIncident:
    now = datetime.now(UTC)
    if action == "acknowledge" and item.status == "open": item.status = "acknowledged"; item.acknowledged_at = now
    elif action == "resolve" and item.status in {"open", "acknowledged"}: item.status = "resolved"; item.resolved_at = now; item.resolution_note = note.strip()
    else: raise HTTPException(409, "Incident transition is not allowed from the current state")
    item.updated_by_id = user.id
    _audit(db, user, f"{action.upper()}_OPERATIONAL_INCIDENT", "operational_incident", item.id,
           {"status": item.status}, note.strip())
    db.commit(); db.refresh(item); return item


def write_governance(db: Session, user: User, payload: GovernanceProfileWrite) -> PilotGovernanceProfile:
    item = db.scalar(select(PilotGovernanceProfile).where(PilotGovernanceProfile.organization_id == user.organization_id))
    if item is None:
        item = PilotGovernanceProfile(organization_id=user.organization_id, created_by_id=user.id); db.add(item)
    for field, value in payload.model_dump().items(): setattr(item, field, str(value).strip())
    item.status = "draft"; item.approved_at = None; item.approved_by_id = None
    db.flush(); _audit(db, user, "WRITE_PILOT_GOVERNANCE_PROFILE", "pilot_governance_profile", item.id,
        {"status": item.status, "data_owner": item.data_owner, "exit_contact": item.exit_contact},
        "Governance statements recorded; approval required before exit manifests.")
    db.commit(); db.refresh(item); return item


def get_governance(db: Session, org: UUID) -> PilotGovernanceProfile:
    item = db.scalar(select(PilotGovernanceProfile).where(PilotGovernanceProfile.organization_id == org))
    if item is None: raise HTTPException(404, "Pilot governance profile not found")
    return item


def approve_governance(db: Session, user: User, item: PilotGovernanceProfile, confirm: bool, note: str):
    if not confirm: raise HTTPException(422, "Explicit governance approval is required")
    item.status = "approved"; item.approved_by_id = user.id; item.approved_at = datetime.now(UTC)
    _audit(db, user, "APPROVE_PILOT_GOVERNANCE_PROFILE", "pilot_governance_profile", item.id,
           {"status": item.status, "approved_at": item.approved_at.isoformat()}, note.strip())
    db.commit(); db.refresh(item); return item


def create_exit_manifest(db: Session, user: User, claim_id: UUID, key: str, confirm: bool) -> PilotExitManifest:
    if not confirm: raise HTTPException(422, "Manifest-only export confirmation is required")
    existing = db.scalar(select(PilotExitManifest).where(PilotExitManifest.organization_id == user.organization_id,
        PilotExitManifest.claim_id == claim_id, PilotExitManifest.idempotency_key == key))
    if existing is not None: return existing
    profile = get_governance(db, user.organization_id)
    if profile.status != "approved": raise HTTPException(409, "Approved pilot governance is required")
    claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.organization_id == user.organization_id))
    if claim is None: raise HTTPException(404, "Claim not found")
    counts = {
        "documents": db.scalar(select(func.count()).select_from(Document).where(Document.organization_id == user.organization_id, Document.claim_id == claim.id, Document.deleted_at.is_(None))) or 0,
        "correspondence": db.scalar(select(func.count()).select_from(ClaimCorrespondence).where(ClaimCorrespondence.organization_id == user.organization_id, ClaimCorrespondence.claim_id == claim.id)) or 0,
        "portal_submissions": db.scalar(select(func.count()).select_from(ExternalPortalSubmission).where(ExternalPortalSubmission.organization_id == user.organization_id, ExternalPortalSubmission.claim_id == claim.id)) or 0,
        "linked_email_messages": db.scalar(select(func.count()).select_from(IngestedEmailMessage).where(IngestedEmailMessage.organization_id == user.organization_id, IngestedEmailMessage.linked_claim_id == claim.id)) or 0,
    }
    manifest = {"schema": "mcri-pilot-exit-manifest-v1", "claim_id": str(claim.id),
                "claim_reference": claim.claim_reference, "counts": counts,
                "governance_profile_id": str(profile.id), "generated_at": datetime.now(UTC).isoformat(),
                "content_included": False, "deletion_performed": False}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")); now = datetime.now(UTC)
    item = PilotExitManifest(organization_id=user.organization_id, claim_id=claim.id,
        governance_profile_id=profile.id, authorized_by_id=user.id, idempotency_key=key,
        confirm_manifest_only=True, manifest=manifest, manifest_checksum=sha256(canonical.encode()).hexdigest(),
        status="authorized", authorized_at=now)
    db.add(item); db.flush()
    _audit(db, user, "AUTHORIZE_PILOT_EXIT_MANIFEST", "pilot_exit_manifest", item.id,
           {"claim_id": str(claim.id), "manifest_checksum": item.manifest_checksum, "counts": counts},
           "Manifest and checksum only; no raw file/message content exported and no deletion performed.")
    db.commit(); db.refresh(item); return item


def _evidence(db: Session, rehearsal_id: UUID) -> list[RehearsalControlEvidence]:
    return list(db.scalars(select(RehearsalControlEvidence).where(
        RehearsalControlEvidence.rehearsal_id == rehearsal_id).order_by(RehearsalControlEvidence.control_key.asc())))


def _findings(db: Session, rehearsal_id: UUID) -> list[RehearsalRemediationFinding]:
    return list(db.scalars(select(RehearsalRemediationFinding).where(
        RehearsalRemediationFinding.rehearsal_id == rehearsal_id).order_by(RehearsalRemediationFinding.created_at.asc())))


def rehearsal_response(db: Session, item: DesignPartnerRehearsal) -> dict:
    return {
        "id": item.id, "readiness_review_id": item.readiness_review_id,
        "rehearsal_key": item.rehearsal_key, "name": item.name,
        "objectives": item.objectives, "participant_roles": item.participant_roles,
        "status": item.status, "scheduled_for": item.scheduled_for,
        "started_at": item.started_at, "completed_at": item.completed_at,
        "outcome": item.outcome, "decision_note": item.decision_note,
        "decision_hash": item.decision_hash, "created_at": item.created_at,
        "evidence": _evidence(db, item.id), "findings": _findings(db, item.id),
    }


def list_rehearsals(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(DesignPartnerRehearsal).where(
        DesignPartnerRehearsal.organization_id == organization_id
    ).order_by(DesignPartnerRehearsal.created_at.desc()).limit(25)))
    return [rehearsal_response(db, item) for item in items]


def get_rehearsal(db: Session, organization_id: UUID, item_id: UUID) -> DesignPartnerRehearsal:
    item = db.scalar(select(DesignPartnerRehearsal).where(
        DesignPartnerRehearsal.id == item_id,
        DesignPartnerRehearsal.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Design-partner rehearsal not found")
    return item


def create_rehearsal(db: Session, user: User, payload: RehearsalCreate) -> dict:
    readiness = get_readiness(db, user.organization_id, payload.readiness_review_id)
    if readiness.status != "ready" or readiness.attested_at is None:
        raise HTTPException(409, "An attested ready snapshot is required before rehearsal")
    objectives = list(dict.fromkeys(value.strip() for value in payload.objectives if value.strip()))
    roles = list(dict.fromkeys(value.strip() for value in payload.participant_roles if value.strip()))
    if not objectives or not roles: raise HTTPException(422, "Objectives and participant roles cannot be blank")
    item = DesignPartnerRehearsal(
        organization_id=user.organization_id, readiness_review_id=readiness.id, created_by_id=user.id,
        rehearsal_key=payload.rehearsal_key.strip(), name=payload.name.strip(), objectives=objectives,
        participant_roles=roles, status="draft", scheduled_for=payload.scheduled_for,
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This rehearsal key already exists") from exc
    _audit(db, user, "CREATE_DESIGN_PARTNER_REHEARSAL", "design_partner_rehearsal", item.id,
           {"readiness_review_id": str(readiness.id), "rehearsal_key": item.rehearsal_key,
            "objective_count": len(objectives), "participant_role_count": len(roles)},
           "Rehearsal created against an attested readiness snapshot; evidence references required.")
    db.commit(); db.refresh(item); return rehearsal_response(db, item)


def start_rehearsal(db: Session, user: User, item: DesignPartnerRehearsal) -> dict:
    if item.status != "draft": raise HTTPException(409, "Only a draft rehearsal can be started")
    item.status = "in_progress"; item.started_at = datetime.now(UTC)
    _audit(db, user, "START_DESIGN_PARTNER_REHEARSAL", "design_partner_rehearsal", item.id,
           {"status": item.status, "started_at": item.started_at.isoformat()},
           "Human-facilitated rehearsal started; no deployment action performed.")
    db.commit(); db.refresh(item); return rehearsal_response(db, item)


def write_rehearsal_evidence(db: Session, user: User, item: DesignPartnerRehearsal,
                             payload: RehearsalEvidenceWrite) -> dict:
    if item.status == "completed": raise HTTPException(409, "Completed rehearsal evidence is immutable")
    if not EVIDENCE_REFERENCE.fullmatch(payload.evidence_reference.strip()):
        raise HTTPException(422, "Evidence reference must use artifact://, runbook://, ticket:// or monitor:// without secrets")
    if item.status == "draft": item.status = "in_progress"; item.started_at = datetime.now(UTC)
    evidence = db.scalar(select(RehearsalControlEvidence).where(
        RehearsalControlEvidence.rehearsal_id == item.id,
        RehearsalControlEvidence.control_key == payload.control_key,
    ))
    if evidence is None:
        evidence = RehearsalControlEvidence(organization_id=user.organization_id, rehearsal_id=item.id,
                                             control_key=payload.control_key); db.add(evidence)
    evidence.recorded_by_id = user.id; evidence.evidence_reference = payload.evidence_reference.strip()
    evidence.evidence_summary = payload.evidence_summary.strip(); evidence.result = payload.result
    evidence.recorded_at = datetime.now(UTC); db.flush()
    _audit(db, user, "RECORD_REHEARSAL_CONTROL_EVIDENCE", "rehearsal_control_evidence", evidence.id,
           {"rehearsal_id": str(item.id), "control_key": evidence.control_key,
            "evidence_reference": evidence.evidence_reference, "result": evidence.result},
           "Bounded reference and human result only; no secret value or raw evidence content stored.")
    db.commit(); db.refresh(evidence); return rehearsal_response(db, item)


def create_rehearsal_finding(db: Session, user: User, item: DesignPartnerRehearsal,
                             payload: RehearsalFindingCreate) -> dict:
    if item.status == "completed": raise HTTPException(409, "Completed rehearsal findings are immutable")
    if payload.evidence_id:
        evidence = db.scalar(select(RehearsalControlEvidence).where(
            RehearsalControlEvidence.id == payload.evidence_id,
            RehearsalControlEvidence.rehearsal_id == item.id,
            RehearsalControlEvidence.organization_id == user.organization_id,
        ))
        if evidence is None: raise HTTPException(404, "Rehearsal evidence not found")
    finding = RehearsalRemediationFinding(
        organization_id=user.organization_id, rehearsal_id=item.id, evidence_id=payload.evidence_id,
        created_by_id=user.id, updated_by_id=user.id, severity=payload.severity,
        title=payload.title.strip(), description=payload.description.strip(),
        owner_label=payload.owner_label.strip(), due_at=payload.due_at, status="open",
    )
    db.add(finding); db.flush()
    _audit(db, user, "OPEN_REHEARSAL_REMEDIATION_FINDING", "rehearsal_remediation_finding", finding.id,
           {"rehearsal_id": str(item.id), "severity": finding.severity, "status": finding.status,
            "owner_label": finding.owner_label, "due_at": finding.due_at.isoformat()},
           finding.description)
    db.commit(); db.refresh(finding); return rehearsal_response(db, item)


def get_rehearsal_finding(db: Session, organization_id: UUID, finding_id: UUID) -> RehearsalRemediationFinding:
    item = db.scalar(select(RehearsalRemediationFinding).where(
        RehearsalRemediationFinding.id == finding_id,
        RehearsalRemediationFinding.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Rehearsal finding not found")
    return item


def transition_rehearsal_finding(db: Session, user: User, rehearsal: DesignPartnerRehearsal,
                                 finding: RehearsalRemediationFinding, action: str, note: str) -> dict:
    if finding.rehearsal_id != rehearsal.id: raise HTTPException(404, "Rehearsal finding not found")
    if rehearsal.status == "completed": raise HTTPException(409, "Completed rehearsal findings are immutable")
    now = datetime.now(UTC)
    if action == "acknowledge" and finding.status == "open":
        finding.status = "acknowledged"; finding.acknowledged_at = now
    elif action == "resolve" and finding.status in {"open", "acknowledged"}:
        finding.status = "resolved"; finding.resolved_at = now; finding.resolution_note = note.strip()
    else: raise HTTPException(409, "Finding transition is not allowed from the current state")
    finding.updated_by_id = user.id
    _audit(db, user, f"{action.upper()}_REHEARSAL_FINDING", "rehearsal_remediation_finding", finding.id,
           {"status": finding.status}, note.strip())
    db.commit(); db.refresh(finding); return rehearsal_response(db, rehearsal)


def complete_rehearsal(db: Session, user: User, item: DesignPartnerRehearsal,
                       outcome: str, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit rehearsal decision confirmation is required")
    if item.status == "completed": raise HTTPException(409, "Rehearsal is already complete")
    evidence = _evidence(db, item.id); findings = _findings(db, item.id)
    evidence_by_control = {entry.control_key: entry for entry in evidence}
    if set(evidence_by_control) != READINESS_CONTROLS:
        raise HTTPException(409, "All eight readiness controls require rehearsal evidence")
    open_findings = [entry for entry in findings if entry.status != "resolved"]
    failed_controls = [key for key, entry in evidence_by_control.items() if entry.result != "pass"]
    if outcome == "go" and (failed_controls or open_findings):
        raise HTTPException(409, "Go is blocked by failed/not-tested controls or unresolved findings")
    now = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-design-partner-rehearsal-v1", "rehearsal_id": str(item.id),
        "readiness_review_id": str(item.readiness_review_id), "rehearsal_key": item.rehearsal_key,
        "outcome": outcome, "decision_note": note.strip(),
        "evidence": [{"control_key": entry.control_key, "reference": entry.evidence_reference,
                      "summary": entry.evidence_summary, "result": entry.result} for entry in evidence],
        "findings": [{"id": str(entry.id), "severity": entry.severity, "title": entry.title,
                      "owner_label": entry.owner_label, "status": entry.status} for entry in findings],
    }
    item.status = "completed"; item.outcome = outcome; item.decision_note = note.strip()
    item.completed_at = now; item.completed_by_id = user.id
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, "COMPLETE_DESIGN_PARTNER_REHEARSAL", "design_partner_rehearsal", item.id,
           {"outcome": item.outcome, "decision_hash": item.decision_hash,
            "evidence_count": len(evidence), "finding_count": len(findings)},
           "Human go/no-go decision snapshot; not a production certification or deployment action. " + item.decision_note)
    db.commit(); db.refresh(item); return rehearsal_response(db, item)


def _case_runs(db: Session, execution_id: UUID) -> list[PrivatePilotCaseRun]:
    return list(db.scalars(select(PrivatePilotCaseRun).where(
        PrivatePilotCaseRun.execution_id == execution_id
    ).order_by(PrivatePilotCaseRun.recorded_at.asc())))


def _product_gaps(db: Session, execution_id: UUID) -> list[ProductGapFinding]:
    return list(db.scalars(select(ProductGapFinding).where(
        ProductGapFinding.execution_id == execution_id
    ).order_by(ProductGapFinding.created_at.asc())))


def _aggregate_pilot_metrics(case_runs: list[PrivatePilotCaseRun],
                             gaps: list[ProductGapFinding]) -> dict:
    outcome_counts = {key: 0 for key in ("completed", "blocked", "abandoned")}
    priority_counts = {key: 0 for key in ("p0", "p1", "p2", "p3")}
    open_priority_counts = {key: 0 for key in ("p0", "p1", "p2", "p3")}
    totals = {
        "triage_minutes": 0, "evidence_review_minutes": 0, "assessment_minutes": 0,
        "adjustment_minutes": 0, "ai_candidates_reviewed": 0, "ai_accepted": 0,
        "ai_edited": 0, "ai_rejected": 0, "rule_findings_reviewed": 0,
        "rule_findings_helpful": 0, "open_conflicts": 0, "open_requirements": 0,
    }
    for item in case_runs:
        outcome_counts[item.case_outcome] = outcome_counts.get(item.case_outcome, 0) + 1
        for field in totals:
            totals[field] += getattr(item, field) or 0
    for gap in gaps:
        priority_counts[gap.priority] = priority_counts.get(gap.priority, 0) + 1
        if gap.status != "resolved":
            open_priority_counts[gap.priority] = open_priority_counts.get(gap.priority, 0) + 1
    return {
        "schema": "mcri-private-pilot-baseline-v1", "case_run_count": len(case_runs),
        "case_outcomes": outcome_counts, "totals": totals,
        "product_gap_count": len(gaps), "priority_counts": priority_counts,
        "open_priority_counts": open_priority_counts,
        "content_included": False,
    }


def pilot_execution_response(db: Session, item: PrivatePilotExecution) -> dict:
    case_runs = _case_runs(db, item.id); gaps = _product_gaps(db, item.id)
    return {
        "id": item.id, "rehearsal_id": item.rehearsal_id, "execution_key": item.execution_key,
        "design_partner_label": item.design_partner_label, "data_mode": item.data_mode,
        "data_authorization_reference": item.data_authorization_reference,
        "objectives": item.objectives, "target_case_runs": item.target_case_runs,
        "status": item.status, "started_at": item.started_at, "completed_at": item.completed_at,
        "outcome": item.outcome, "outcome_note": item.outcome_note,
        "outcome_hash": item.outcome_hash, "created_at": item.created_at,
        "aggregate_metrics": _aggregate_pilot_metrics(case_runs, gaps),
        "case_runs": case_runs, "product_gaps": gaps,
    }


def list_pilot_executions(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(PrivatePilotExecution).where(
        PrivatePilotExecution.organization_id == organization_id
    ).order_by(PrivatePilotExecution.created_at.desc()).limit(25)))
    return [pilot_execution_response(db, item) for item in items]


def get_pilot_execution(db: Session, organization_id: UUID, item_id: UUID) -> PrivatePilotExecution:
    item = db.scalar(select(PrivatePilotExecution).where(
        PrivatePilotExecution.id == item_id,
        PrivatePilotExecution.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Private pilot execution not found")
    return item


def create_pilot_execution(db: Session, user: User, payload: PilotExecutionCreate) -> dict:
    rehearsal = get_rehearsal(db, user.organization_id, payload.rehearsal_id)
    if rehearsal.status != "completed" or rehearsal.outcome != "go":
        raise HTTPException(409, "A completed Go rehearsal is required before private pilot execution")
    reference = payload.data_authorization_reference.strip() if payload.data_authorization_reference else None
    if reference and not EVIDENCE_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Authorization reference must use an allowlisted bounded scheme")
    if payload.data_mode == "approved_real":
        profile = db.scalar(select(PilotGovernanceProfile).where(
            PilotGovernanceProfile.organization_id == user.organization_id))
        if profile is None or profile.status != "approved" or not reference:
            raise HTTPException(409, "Approved governance and a bounded authorization reference are required for real data")
    objectives = list(dict.fromkeys(value.strip() for value in payload.objectives if value.strip()))
    if not objectives: raise HTTPException(422, "Pilot objectives cannot be blank")
    item = PrivatePilotExecution(
        organization_id=user.organization_id, rehearsal_id=rehearsal.id, created_by_id=user.id,
        execution_key=payload.execution_key.strip(),
        design_partner_label=payload.design_partner_label.strip(), data_mode=payload.data_mode,
        data_authorization_reference=reference, objectives=objectives,
        target_case_runs=payload.target_case_runs, status="draft",
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This execution key or rehearsal is already in use") from exc
    _audit(db, user, "CREATE_PRIVATE_PILOT_EXECUTION", "private_pilot_execution", item.id,
           {"rehearsal_id": str(rehearsal.id), "data_mode": item.data_mode,
            "target_case_runs": item.target_case_runs, "authorization_reference": reference},
           "Execution plan only; no pilot, notification or evidence processing started automatically.")
    db.commit(); db.refresh(item); return pilot_execution_response(db, item)


def start_pilot_execution(db: Session, user: User, item: PrivatePilotExecution) -> dict:
    if item.status != "draft": raise HTTPException(409, "Only a draft pilot execution can be started")
    item.status = "in_progress"; item.started_at = datetime.now(UTC)
    _audit(db, user, "START_PRIVATE_PILOT_EXECUTION", "private_pilot_execution", item.id,
           {"status": item.status, "started_at": item.started_at.isoformat()},
           "Human-authorized private pilot execution started; no external notification was sent.")
    db.commit(); db.refresh(item); return pilot_execution_response(db, item)


def write_pilot_case_run(db: Session, user: User, execution: PrivatePilotExecution,
                         payload: PilotCaseRunWrite) -> dict:
    if execution.status == "draft":
        raise HTTPException(409, "A Manager or Admin must start the pilot execution before case runs")
    if execution.status == "completed": raise HTTPException(409, "Completed pilot execution is immutable")
    if not EVIDENCE_REFERENCE.fullmatch(payload.evidence_reference.strip()):
        raise HTTPException(422, "Case-run evidence must use an allowlisted bounded reference")
    if payload.ai_accepted + payload.ai_edited + payload.ai_rejected != payload.ai_candidates_reviewed:
        raise HTTPException(422, "AI review decisions must equal the reviewed candidate count")
    if payload.rule_findings_helpful > payload.rule_findings_reviewed:
        raise HTTPException(422, "Helpful rule findings cannot exceed reviewed rule findings")
    claim = db.scalar(select(Claim).where(
        Claim.id == payload.claim_id, Claim.organization_id == user.organization_id,
        Claim.deleted_at.is_(None),
    ))
    if claim is None: raise HTTPException(404, "Claim not found")
    item = db.scalar(select(PrivatePilotCaseRun).where(
        PrivatePilotCaseRun.execution_id == execution.id,
        PrivatePilotCaseRun.claim_id == claim.id,
    ))
    action = "UPDATE_PRIVATE_PILOT_CASE_RUN" if item else "RECORD_PRIVATE_PILOT_CASE_RUN"
    if item is None:
        item = PrivatePilotCaseRun(organization_id=user.organization_id,
                                   execution_id=execution.id, claim_id=claim.id)
        db.add(item)
    for field, value in payload.model_dump(exclude={"claim_id"}).items():
        setattr(item, field, value.strip() if isinstance(value, str) else value)
    item.recorded_by_id = user.id; item.recorded_at = datetime.now(UTC); db.flush()
    _audit(db, user, action, "private_pilot_case_run", item.id,
           {"execution_id": str(execution.id), "claim_id": str(claim.id),
            "case_outcome": item.case_outcome, "ai_candidates_reviewed": item.ai_candidates_reviewed,
            "rule_findings_reviewed": item.rule_findings_reviewed,
            "evidence_reference": item.evidence_reference},
           "Bounded workflow measurements only; no claim narrative, evidence text or personal data stored.")
    db.commit(); db.refresh(item); return pilot_execution_response(db, execution)


def create_product_gap(db: Session, user: User, execution: PrivatePilotExecution,
                       payload: ProductGapCreate) -> dict:
    if execution.status == "draft":
        raise HTTPException(409, "A Manager or Admin must start the pilot execution before product gaps")
    if execution.status == "completed": raise HTTPException(409, "Completed pilot execution is immutable")
    if payload.evidence_reference and not EVIDENCE_REFERENCE.fullmatch(payload.evidence_reference.strip()):
        raise HTTPException(422, "Gap evidence must use an allowlisted bounded reference")
    if payload.case_run_id:
        case_run = db.scalar(select(PrivatePilotCaseRun).where(
            PrivatePilotCaseRun.id == payload.case_run_id,
            PrivatePilotCaseRun.execution_id == execution.id,
            PrivatePilotCaseRun.organization_id == user.organization_id,
        ))
        if case_run is None: raise HTTPException(404, "Pilot case run not found")
    item = ProductGapFinding(
        organization_id=user.organization_id, execution_id=execution.id,
        case_run_id=payload.case_run_id, created_by_id=user.id, updated_by_id=user.id,
        priority=payload.priority, category=payload.category, title=payload.title.strip(),
        summary=payload.summary.strip(), owner_label=payload.owner_label.strip(),
        due_at=payload.due_at,
        evidence_reference=payload.evidence_reference.strip() if payload.evidence_reference else None,
        status="open",
    )
    db.add(item); db.flush()
    _audit(db, user, "OPEN_PRODUCT_GAP", "product_gap_finding", item.id,
           {"execution_id": str(execution.id), "priority": item.priority,
            "category": item.category, "owner_label": item.owner_label,
            "evidence_reference": item.evidence_reference},
           item.summary)
    db.commit(); db.refresh(item); return pilot_execution_response(db, execution)


def get_product_gap(db: Session, organization_id: UUID, gap_id: UUID) -> ProductGapFinding:
    item = db.scalar(select(ProductGapFinding).where(
        ProductGapFinding.id == gap_id, ProductGapFinding.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Product gap not found")
    return item


def transition_product_gap(db: Session, user: User, execution: PrivatePilotExecution,
                           gap: ProductGapFinding, action: str, note: str) -> dict:
    if gap.execution_id != execution.id: raise HTTPException(404, "Product gap not found")
    if execution.status == "completed": raise HTTPException(409, "Completed pilot execution is immutable")
    allowed = {"accept": "accepted", "resolve": "resolved", "wont_fix": "wont_fix"}
    if action not in allowed or gap.status in {"resolved", "wont_fix"}:
        raise HTTPException(409, "Product-gap transition is not allowed from the current state")
    gap.status = allowed[action]; gap.resolution_note = note.strip(); gap.updated_by_id = user.id
    if gap.status in {"resolved", "wont_fix"}: gap.resolved_at = datetime.now(UTC)
    _audit(db, user, f"{action.upper()}_PRODUCT_GAP", "product_gap_finding", gap.id,
           {"status": gap.status}, note.strip())
    db.commit(); db.refresh(gap); return pilot_execution_response(db, execution)


def complete_pilot_execution(db: Session, user: User, item: PrivatePilotExecution,
                             outcome: str, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit pilot outcome confirmation is required")
    if item.status == "completed": raise HTTPException(409, "Pilot execution is already complete")
    case_runs = _case_runs(db, item.id); gaps = _product_gaps(db, item.id)
    if len(case_runs) < item.target_case_runs:
        raise HTTPException(409, "The target number of pilot case runs has not been recorded")
    blocking_p0 = [gap for gap in gaps if gap.priority == "p0" and gap.status != "resolved"]
    if outcome == "proceed" and blocking_p0:
        raise HTTPException(409, "Proceed is blocked until every P0 product gap is resolved")
    metrics = _aggregate_pilot_metrics(case_runs, gaps)
    snapshot = {
        "schema": "mcri-private-pilot-outcome-v1", "execution_id": str(item.id),
        "rehearsal_id": str(item.rehearsal_id), "execution_key": item.execution_key,
        "data_mode": item.data_mode, "outcome": outcome, "outcome_note": note.strip(),
        "aggregate_metrics": metrics,
        "product_gaps": [{"id": str(gap.id), "priority": gap.priority,
                          "category": gap.category, "status": gap.status} for gap in gaps],
    }
    item.status = "completed"; item.outcome = outcome; item.outcome_note = note.strip()
    item.completed_at = datetime.now(UTC); item.completed_by_id = user.id
    item.outcome_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, "COMPLETE_PRIVATE_PILOT_EXECUTION", "private_pilot_execution", item.id,
           {"outcome": item.outcome, "outcome_hash": item.outcome_hash,
            "case_run_count": len(case_runs), "product_gap_count": len(gaps)},
           "Human pilot outcome snapshot; not a production certification. " + item.outcome_note)
    db.commit(); db.refresh(item); return pilot_execution_response(db, item)


def _architecture_controls(db: Session, baseline_id: UUID) -> list[ProductionArchitectureControl]:
    return list(db.scalars(select(ProductionArchitectureControl).where(
        ProductionArchitectureControl.baseline_id == baseline_id
    ).order_by(ProductionArchitectureControl.control_key.asc())))


def _architecture_summary(controls: list[ProductionArchitectureControl]) -> dict:
    states = {key: 0 for key in ("missing", "partial", "implemented", "not_applicable")}
    for item in controls: states[item.current_state] = states.get(item.current_state, 0) + 1
    return {"required_control_count": len(ARCHITECTURE_CONTROLS),
            "documented_control_count": len(controls), "state_counts": states,
            "production_certification": False}


def architecture_baseline_response(db: Session, item: ProductionArchitectureBaseline) -> dict:
    controls = _architecture_controls(db, item.id)
    return {
        "id": item.id, "pilot_execution_id": item.pilot_execution_id,
        "baseline_key": item.baseline_key, "deployment_model": item.deployment_model,
        "data_residency_region": item.data_residency_region, "status": item.status,
        "snapshot_hash": item.snapshot_hash, "attestation_note": item.attestation_note,
        "attested_at": item.attested_at, "created_at": item.created_at,
        "summary": _architecture_summary(controls), "controls": controls,
    }


def list_architecture_baselines(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(ProductionArchitectureBaseline).where(
        ProductionArchitectureBaseline.organization_id == organization_id
    ).order_by(ProductionArchitectureBaseline.created_at.desc()).limit(25)))
    return [architecture_baseline_response(db, item) for item in items]


def get_architecture_baseline(db: Session, organization_id: UUID,
                              item_id: UUID) -> ProductionArchitectureBaseline:
    item = db.scalar(select(ProductionArchitectureBaseline).where(
        ProductionArchitectureBaseline.id == item_id,
        ProductionArchitectureBaseline.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Production architecture baseline not found")
    return item


def create_architecture_baseline(db: Session, user: User,
                                 payload: ArchitectureBaselineCreate) -> dict:
    execution = get_pilot_execution(db, user.organization_id, payload.pilot_execution_id)
    if execution.status != "completed":
        raise HTTPException(409, "A completed private pilot execution is required before architecture baseline")
    item = ProductionArchitectureBaseline(
        organization_id=user.organization_id, pilot_execution_id=execution.id,
        created_by_id=user.id, baseline_key=payload.baseline_key.strip(),
        deployment_model=payload.deployment_model,
        data_residency_region=payload.data_residency_region.strip(), status="draft",
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This production architecture baseline key already exists") from exc
    _audit(db, user, "CREATE_PRODUCTION_ARCHITECTURE_BASELINE", "production_architecture_baseline", item.id,
           {"pilot_execution_id": str(execution.id), "deployment_model": item.deployment_model,
            "data_residency_region": item.data_residency_region},
           "Architecture design baseline only; no infrastructure was deployed or certified.")
    db.commit(); db.refresh(item); return architecture_baseline_response(db, item)


def write_architecture_control(db: Session, user: User, baseline: ProductionArchitectureBaseline,
                               payload: ArchitectureControlWrite) -> dict:
    if baseline.attested_at is not None:
        raise HTTPException(409, "Attested architecture baseline is immutable")
    reference = payload.evidence_reference.strip() if payload.evidence_reference else None
    if reference and not EVIDENCE_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Architecture evidence must use an allowlisted bounded reference")
    item = db.scalar(select(ProductionArchitectureControl).where(
        ProductionArchitectureControl.baseline_id == baseline.id,
        ProductionArchitectureControl.control_key == payload.control_key,
    ))
    if item is None:
        item = ProductionArchitectureControl(
            organization_id=user.organization_id, baseline_id=baseline.id,
            control_key=payload.control_key,
        ); db.add(item)
    item.recorded_by_id = user.id; item.current_state = payload.current_state
    item.target_architecture = payload.target_architecture.strip()
    item.risk_note = payload.risk_note.strip(); item.owner_label = payload.owner_label.strip()
    item.target_date = payload.target_date; item.evidence_reference = reference
    db.flush()
    recorded_keys = {entry.control_key for entry in _architecture_controls(db, baseline.id)}
    baseline.status = "review_ready" if recorded_keys == ARCHITECTURE_CONTROLS else "draft"
    _audit(db, user, "RECORD_PRODUCTION_ARCHITECTURE_CONTROL", "production_architecture_control", item.id,
           {"baseline_id": str(baseline.id), "control_key": item.control_key,
            "current_state": item.current_state, "owner_label": item.owner_label,
            "target_date": item.target_date.isoformat(), "evidence_reference": reference},
           "Current gap and target design recorded; no compliance or readiness conclusion generated.")
    db.commit(); db.refresh(item); return architecture_baseline_response(db, baseline)


def attest_architecture_baseline(db: Session, user: User, item: ProductionArchitectureBaseline,
                                 confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit architecture review confirmation is required")
    if item.attested_at is not None: raise HTTPException(409, "Architecture baseline is already attested")
    controls = _architecture_controls(db, item.id)
    if {entry.control_key for entry in controls} != ARCHITECTURE_CONTROLS:
        raise HTTPException(409, "All nine production architecture controls must be documented")
    snapshot = {
        "schema": "mcri-production-architecture-baseline-v1", "baseline_id": str(item.id),
        "pilot_execution_id": str(item.pilot_execution_id), "baseline_key": item.baseline_key,
        "deployment_model": item.deployment_model, "data_residency_region": item.data_residency_region,
        "controls": [{"control_key": entry.control_key, "current_state": entry.current_state,
                      "target_architecture": entry.target_architecture, "risk_note": entry.risk_note,
                      "owner_label": entry.owner_label, "target_date": entry.target_date.isoformat(),
                      "evidence_reference": entry.evidence_reference} for entry in controls],
        "production_certification": False,
    }
    has_gaps = any(entry.current_state in {"missing", "partial"} for entry in controls)
    item.status = "attested_with_gaps" if has_gaps else "attested_baseline"
    item.snapshot_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    item.attestation_note = note.strip(); item.attested_at = datetime.now(UTC); item.attested_by_id = user.id
    _audit(db, user, "ATTEST_PRODUCTION_ARCHITECTURE_BASELINE", "production_architecture_baseline", item.id,
           {"status": item.status, "snapshot_hash": item.snapshot_hash,
            "state_counts": _architecture_summary(controls)["state_counts"]},
           "Human-reviewed architecture baseline; not a production, regulatory or compliance certification. " + item.attestation_note)
    db.commit(); db.refresh(item); return architecture_baseline_response(db, item)


def _control_evidence(db: Session, gate_id: UUID) -> list[ProductionControlEvidence]:
    return list(db.scalars(select(ProductionControlEvidence).where(
        ProductionControlEvidence.gate_id == gate_id
    ).order_by(ProductionControlEvidence.control_key.asc(),
               ProductionControlEvidence.submission_version.asc())))


def _current_control_evidence(items: list[ProductionControlEvidence]) -> dict[str, ProductionControlEvidence]:
    current: dict[str, ProductionControlEvidence] = {}
    for item in items:
        current[item.control_key] = item
    return current


def _required_production_controls(item: ProductionControlVerificationGate) -> set[str]:
    required = CONTROL_VERIFICATION_PROFILES.get(item.verification_profile)
    if required is None:
        raise HTTPException(409, "The verification gate uses an unsupported control profile")
    return required


def _control_gate_summary(gate: ProductionControlVerificationGate,
                          items: list[ProductionControlEvidence]) -> dict:
    required_controls = _required_production_controls(gate)
    current = _current_control_evidence(items)
    status_counts = {key: 0 for key in ("not_submitted", "submitted", "verified", "rejected")}
    for control in required_controls:
        item = current.get(control)
        status_counts[item.status if item else "not_submitted"] += 1
    return {
        "verification_profile": gate.verification_profile,
        "required_control_count": len(required_controls),
        "required_controls": sorted(required_controls),
        "current_submission_count": sum(control in current for control in required_controls),
        "total_submission_count": len(items),
        "status_counts": status_counts,
        "all_independently_verified": (
            set(current) == required_controls
            and all(current[control].status == "verified"
                    and current[control].reviewed_by_id != current[control].submitted_by_id
                    for control in required_controls)
        ),
        "production_certification": False,
        "go_live_authorization": False,
        "content_or_secrets_included": False,
    }


def control_verification_gate_response(db: Session,
                                       item: ProductionControlVerificationGate) -> dict:
    evidence = _control_evidence(db, item.id)
    return {
        "id": item.id, "architecture_baseline_id": item.architecture_baseline_id,
        "gate_key": item.gate_key, "verification_profile": item.verification_profile,
        "status": item.status,
        "outcome_note": item.outcome_note, "outcome_hash": item.outcome_hash,
        "completed_at": item.completed_at, "created_at": item.created_at,
        "summary": _control_gate_summary(item, evidence), "evidence": evidence,
    }


def list_control_verification_gates(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(ProductionControlVerificationGate).where(
        ProductionControlVerificationGate.organization_id == organization_id
    ).order_by(ProductionControlVerificationGate.created_at.desc()).limit(25)))
    return [control_verification_gate_response(db, item) for item in items]


def get_control_verification_gate(db: Session, organization_id: UUID,
                                  item_id: UUID) -> ProductionControlVerificationGate:
    item = db.scalar(select(ProductionControlVerificationGate).where(
        ProductionControlVerificationGate.id == item_id,
        ProductionControlVerificationGate.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Production control verification gate not found")
    return item


def create_control_verification_gate(db: Session, user: User,
                                     payload: ControlVerificationGateCreate) -> dict:
    baseline = get_architecture_baseline(db, user.organization_id,
                                         payload.architecture_baseline_id)
    if baseline.attested_at is None:
        raise HTTPException(409, "An attested production architecture baseline is required")
    item = ProductionControlVerificationGate(
        organization_id=user.organization_id, architecture_baseline_id=baseline.id,
        created_by_id=user.id, gate_key=payload.gate_key.strip(), status="collecting",
        verification_profile=LATEST_CONTROL_VERIFICATION_PROFILE,
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(
            409, "This verification gate key or architecture baseline is already in use") from exc
    _audit(db, user, "CREATE_PRODUCTION_CONTROL_VERIFICATION_GATE",
           "production_control_verification_gate", item.id,
           {"architecture_baseline_id": str(baseline.id), "gate_key": item.gate_key,
            "verification_profile": item.verification_profile,
            "required_controls": sorted(_required_production_controls(item))},
           "Verification workflow only; no infrastructure deployment or certification occurred.")
    db.commit(); db.refresh(item); return control_verification_gate_response(db, item)


def submit_production_control_evidence(db: Session, user: User,
                                       gate: ProductionControlVerificationGate,
                                       payload: ProductionControlEvidenceSubmit) -> dict:
    if gate.status == "completed": raise HTTPException(409, "Completed verification gate is immutable")
    if payload.implementation_completed_at.tzinfo is None or payload.implementation_completed_at.utcoffset() is None:
        raise HTTPException(422, "Implementation completion time must include a timezone")
    if payload.implementation_completed_at > datetime.now(UTC):
        raise HTTPException(422, "Implementation completion time cannot be in the future")
    reference = payload.evidence_reference.strip()
    if not EVIDENCE_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Implementation evidence must use an allowlisted bounded reference")
    if payload.control_key not in _required_production_controls(gate):
        raise HTTPException(409, "This control is not part of the gate's immutable verification profile")
    evidence = _control_evidence(db, gate.id)
    latest = _current_control_evidence(evidence).get(payload.control_key)
    if latest is not None and latest.status in {"submitted", "verified"}:
        raise HTTPException(409, "The current control evidence must be reviewed before resubmission")
    version = latest.submission_version + 1 if latest else 1
    item = ProductionControlEvidence(
        organization_id=user.organization_id, gate_id=gate.id,
        submitted_by_id=user.id, control_key=payload.control_key,
        submission_version=version,
        implementation_summary=payload.implementation_summary.strip(),
        verification_method=payload.verification_method.strip(),
        rollback_plan=payload.rollback_plan.strip(), owner_label=payload.owner_label.strip(),
        implementation_completed_at=payload.implementation_completed_at,
        evidence_reference=reference, status="submitted", submitted_at=datetime.now(UTC),
    )
    db.add(item); gate.status = "collecting"; db.flush()
    _audit(db, user, "SUBMIT_PRODUCTION_CONTROL_EVIDENCE", "production_control_evidence",
           item.id, {"gate_id": str(gate.id), "control_key": item.control_key,
                     "submission_version": item.submission_version,
                     "owner_label": item.owner_label, "evidence_reference": reference},
           "Bounded implementation statement only; no secret, raw artifact or claim content stored.")
    db.commit(); db.refresh(item); return control_verification_gate_response(db, gate)


def get_production_control_evidence(db: Session, organization_id: UUID,
                                    evidence_id: UUID) -> ProductionControlEvidence:
    item = db.scalar(select(ProductionControlEvidence).where(
        ProductionControlEvidence.id == evidence_id,
        ProductionControlEvidence.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "Production control evidence not found")
    return item


def review_production_control_evidence(db: Session, user: User,
                                       gate: ProductionControlVerificationGate,
                                       evidence: ProductionControlEvidence,
                                       action: str, review_reference: str | None,
                                       note: str) -> dict:
    if gate.status == "completed": raise HTTPException(409, "Completed verification gate is immutable")
    if evidence.gate_id != gate.id: raise HTTPException(404, "Production control evidence not found")
    if evidence.status != "submitted": raise HTTPException(409, "Only submitted evidence can be reviewed")
    if evidence.submitted_by_id == user.id:
        raise HTTPException(409, "A different Manager or Admin must independently review this evidence")
    reference = review_reference.strip() if review_reference else None
    if action == "verify" and not reference:
        raise HTTPException(422, "Verified control evidence requires a bounded review reference")
    if reference and not EVIDENCE_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Review evidence must use an allowlisted bounded reference")
    evidence.status = "verified" if action == "verify" else "rejected"
    evidence.reviewed_by_id = user.id; evidence.review_reference = reference
    evidence.review_note = note.strip(); evidence.reviewed_at = datetime.now(UTC)
    db.flush()
    current = _current_control_evidence(_control_evidence(db, gate.id))
    required_controls = _required_production_controls(gate)
    gate.status = "review_ready" if (
        set(current) == required_controls
        and all(current[control].status == "verified" for control in required_controls)
    ) else "collecting"
    _audit(db, user, f"{action.upper()}_PRODUCTION_CONTROL_EVIDENCE",
           "production_control_evidence", evidence.id,
           {"gate_id": str(gate.id), "control_key": evidence.control_key,
            "submission_version": evidence.submission_version, "status": evidence.status,
            "review_reference": reference},
           "Independent human review; no automated control conclusion or deployment action. " + note.strip())
    db.commit(); db.refresh(evidence); return control_verification_gate_response(db, gate)


def complete_control_verification_gate(db: Session, user: User,
                                       item: ProductionControlVerificationGate,
                                       confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit verification-gate confirmation is required")
    if item.status == "completed": raise HTTPException(409, "Verification gate is already complete")
    evidence = _control_evidence(db, item.id); current = _current_control_evidence(evidence)
    required_controls = _required_production_controls(item)
    if set(current) != required_controls or any(
        current[control].status != "verified"
        or current[control].reviewed_by_id == current[control].submitted_by_id
        for control in required_controls
    ):
        raise HTTPException(
            409, f"All {len(required_controls)} profile controls require independent verification")
    snapshot = {
        "schema": ("mcri-production-control-verification-v1"
                   if item.verification_profile == "foundational_v1"
                   else "mcri-production-control-verification-v2"),
        "gate_id": str(item.id),
        "architecture_baseline_id": str(item.architecture_baseline_id),
        "gate_key": item.gate_key,
        "controls": [{"control_key": entry.control_key,
                      "submission_version": entry.submission_version,
                      "implementation_summary": entry.implementation_summary,
                      "verification_method": entry.verification_method,
                      "rollback_plan": entry.rollback_plan,
                      "owner_label": entry.owner_label,
                      "implementation_completed_at": entry.implementation_completed_at.isoformat(),
                      "evidence_reference": entry.evidence_reference,
                      "review_reference": entry.review_reference,
                      "review_note": entry.review_note} for entry in sorted(
                          current.values(), key=lambda value: value.control_key)],
        "production_certification": False, "go_live_authorization": False,
        "content_or_secrets_included": False,
    }
    if item.verification_profile != "foundational_v1":
        snapshot["verification_profile"] = item.verification_profile
    item.status = "completed"; item.outcome_note = note.strip()
    item.outcome_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
    item.completed_at = datetime.now(UTC); item.completed_by_id = user.id
    _audit(db, user, "COMPLETE_PRODUCTION_CONTROL_VERIFICATION_GATE",
           "production_control_verification_gate", item.id,
           {"outcome_hash": item.outcome_hash, "verified_control_count": len(current),
            "verification_profile": item.verification_profile,
            "production_certification": False, "go_live_authorization": False},
           f"{len(required_controls)}-control evidence snapshot only; not a production "
           "certification or go-live authorization. " + item.outcome_note)
    db.commit(); db.refresh(item); return control_verification_gate_response(db, item)
