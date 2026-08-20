import json
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
    DeploymentReadinessReview, OperationalIncident, OperationalMonitorRun,
    PilotExitManifest, PilotGovernanceProfile,
)
from app.modules.pilot_operations.schemas import (
    GovernanceProfileWrite, IncidentCreate, MonitorRunCreate, ReadinessCreate,
)
from app.modules.users.models import User

READINESS_CONTROLS = {"tls", "secret_references", "backup_restore", "migrations", "malware_scan",
                      "least_privilege", "retention", "incident_contacts"}


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
    return readiness, monitors, incidents, profile, exits


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
