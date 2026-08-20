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
    PilotExitManifest, PilotGovernanceProfile, RehearsalControlEvidence, RehearsalRemediationFinding,
)
from app.modules.pilot_operations.schemas import (
    GovernanceProfileWrite, IncidentCreate, MonitorRunCreate, ReadinessCreate,
    RehearsalCreate, RehearsalEvidenceWrite, RehearsalFindingCreate,
)
from app.modules.users.models import User

READINESS_CONTROLS = {"tls", "secret_references", "backup_restore", "migrations", "malware_scan",
                      "least_privilege", "retention", "incident_contacts"}
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
    return readiness, monitors, incidents, profile, exits, rehearsals


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
