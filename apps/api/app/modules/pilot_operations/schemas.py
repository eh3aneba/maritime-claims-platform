from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ReadinessCreate(BaseModel):
    environment: Literal["staging", "pilot"]
    review_key: str = Field(min_length=8, max_length=120)
    controls: dict[str, bool]


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    environment: str
    review_key: str
    controls: dict
    status: str
    snapshot_hash: str
    attestation_note: str | None
    attested_at: datetime | None
    created_at: datetime


class ReadinessAttest(BaseModel):
    confirm_ready: bool
    note: str = Field(min_length=10, max_length=2000)


class MonitorRunCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    pending_intake_threshold: int = Field(default=50, ge=1, le=10000)
    adapter_failure_threshold: int = Field(default=1, ge=1, le=1000)
    expired_portal_threshold: int = Field(default=10, ge=1, le=10000)


class MonitorRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    idempotency_key: str
    metrics: dict
    alerts: list
    status: str
    run_at: datetime
    created_at: datetime


class IncidentCreate(BaseModel):
    monitor_run_id: UUID | None = None
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["availability", "security", "retention", "provider_adapter", "external_portal", "data_integrity"]
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10, max_length=4000)
    owner_label: str = Field(min_length=2, max_length=180)


class IncidentTransition(BaseModel):
    action: Literal["acknowledge", "resolve"]
    note: str = Field(min_length=5, max_length=4000)


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    monitor_run_id: UUID | None
    severity: str
    category: str
    title: str
    summary: str
    owner_label: str
    status: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime


class GovernanceProfileWrite(BaseModel):
    pilot_purpose: str = Field(min_length=20, max_length=4000)
    legal_basis: str = Field(min_length=10, max_length=4000)
    data_owner: str = Field(min_length=2, max_length=180)
    retention_statement: str = Field(min_length=20, max_length=4000)
    residency_statement: str = Field(min_length=10, max_length=4000)
    exit_contact: EmailStr


class GovernanceApproval(BaseModel):
    confirm_approved: bool
    note: str = Field(min_length=10, max_length=2000)


class GovernanceProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pilot_purpose: str
    legal_basis: str
    data_owner: str
    retention_statement: str
    residency_statement: str
    exit_contact: str
    status: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExitManifestCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    confirm_manifest_only: bool


class ExitManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    governance_profile_id: UUID
    idempotency_key: str
    confirm_manifest_only: bool
    manifest: dict
    manifest_checksum: str
    status: str
    authorized_at: datetime
    created_at: datetime


class RehearsalCreate(BaseModel):
    readiness_review_id: UUID
    rehearsal_key: str = Field(min_length=8, max_length=120)
    name: str = Field(min_length=3, max_length=200)
    objectives: list[str] = Field(min_length=1, max_length=12)
    participant_roles: list[str] = Field(min_length=1, max_length=12)
    scheduled_for: datetime


class RehearsalEvidenceWrite(BaseModel):
    control_key: Literal["tls", "secret_references", "backup_restore", "migrations", "malware_scan", "least_privilege", "retention", "incident_contacts"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    evidence_summary: str = Field(min_length=10, max_length=2000)
    result: Literal["pass", "fail", "not_tested"]


class RehearsalEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rehearsal_id: UUID
    control_key: str
    evidence_reference: str
    evidence_summary: str
    result: str
    recorded_at: datetime
    created_at: datetime


class RehearsalFindingCreate(BaseModel):
    evidence_id: UUID | None = None
    severity: Literal["low", "medium", "high", "critical"]
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=4000)
    owner_label: str = Field(min_length=2, max_length=180)
    due_at: datetime


class RehearsalFindingTransition(BaseModel):
    action: Literal["acknowledge", "resolve"]
    note: str = Field(min_length=5, max_length=4000)


class RehearsalFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rehearsal_id: UUID
    evidence_id: UUID | None
    severity: str
    title: str
    description: str
    owner_label: str
    due_at: datetime
    status: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime


class RehearsalComplete(BaseModel):
    outcome: Literal["go", "no_go"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class RehearsalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    readiness_review_id: UUID
    rehearsal_key: str
    name: str
    objectives: list
    participant_roles: list
    status: str
    scheduled_for: datetime
    started_at: datetime | None
    completed_at: datetime | None
    outcome: str | None
    decision_note: str | None
    decision_hash: str | None
    evidence: list[RehearsalEvidenceResponse]
    findings: list[RehearsalFindingResponse]
    created_at: datetime


class PilotExecutionCreate(BaseModel):
    rehearsal_id: UUID
    execution_key: str = Field(min_length=8, max_length=120)
    design_partner_label: str = Field(min_length=3, max_length=200)
    data_mode: Literal["synthetic", "approved_real"]
    data_authorization_reference: str | None = Field(default=None, min_length=8, max_length=500)
    objectives: list[str] = Field(min_length=1, max_length=12)
    target_case_runs: int = Field(ge=1, le=50)


class PilotCaseRunWrite(BaseModel):
    claim_id: UUID
    case_outcome: Literal["completed", "blocked", "abandoned"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    triage_minutes: int | None = Field(default=None, ge=0, le=10080)
    evidence_review_minutes: int | None = Field(default=None, ge=0, le=10080)
    assessment_minutes: int | None = Field(default=None, ge=0, le=10080)
    adjustment_minutes: int | None = Field(default=None, ge=0, le=10080)
    ai_candidates_reviewed: int = Field(default=0, ge=0, le=100000)
    ai_accepted: int = Field(default=0, ge=0, le=100000)
    ai_edited: int = Field(default=0, ge=0, le=100000)
    ai_rejected: int = Field(default=0, ge=0, le=100000)
    rule_findings_reviewed: int = Field(default=0, ge=0, le=100000)
    rule_findings_helpful: int = Field(default=0, ge=0, le=100000)
    open_conflicts: int = Field(default=0, ge=0, le=100000)
    open_requirements: int = Field(default=0, ge=0, le=100000)


class PilotCaseRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    execution_id: UUID
    claim_id: UUID
    case_outcome: str
    evidence_reference: str
    triage_minutes: int | None
    evidence_review_minutes: int | None
    assessment_minutes: int | None
    adjustment_minutes: int | None
    ai_candidates_reviewed: int
    ai_accepted: int
    ai_edited: int
    ai_rejected: int
    rule_findings_reviewed: int
    rule_findings_helpful: int
    open_conflicts: int
    open_requirements: int
    recorded_at: datetime
    created_at: datetime


class ProductGapCreate(BaseModel):
    case_run_id: UUID | None = None
    priority: Literal["p0", "p1", "p2", "p3"]
    category: Literal["security", "reliability", "workflow", "domain", "ux", "ai", "integration", "commercial", "data_governance"]
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10, max_length=4000)
    owner_label: str = Field(min_length=2, max_length=180)
    due_at: datetime
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)


class ProductGapTransition(BaseModel):
    action: Literal["accept", "resolve", "wont_fix"]
    note: str = Field(min_length=5, max_length=4000)


class ProductGapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    execution_id: UUID
    case_run_id: UUID | None
    priority: str
    category: str
    title: str
    summary: str
    owner_label: str
    due_at: datetime
    evidence_reference: str | None
    status: str
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class PilotExecutionComplete(BaseModel):
    outcome: Literal["proceed", "pause", "stop"]
    confirm_outcome: bool
    note: str = Field(min_length=10, max_length=4000)


class PilotExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rehearsal_id: UUID
    execution_key: str
    design_partner_label: str
    data_mode: str
    data_authorization_reference: str | None
    objectives: list
    target_case_runs: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    outcome: str | None
    outcome_note: str | None
    outcome_hash: str | None
    aggregate_metrics: dict
    case_runs: list[PilotCaseRunResponse]
    product_gaps: list[ProductGapResponse]
    created_at: datetime


class ArchitectureBaselineCreate(BaseModel):
    pilot_execution_id: UUID
    baseline_key: str = Field(min_length=8, max_length=120)
    deployment_model: Literal["single_tenant_managed", "multi_tenant_managed", "on_prem"]
    data_residency_region: str = Field(min_length=2, max_length=120)


class ArchitectureControlWrite(BaseModel):
    control_key: Literal["identity_access", "application_security", "evidence_storage", "observability", "backup_dr", "data_governance", "deployment_iac", "interoperability", "ai_governance"]
    current_state: Literal["missing", "partial", "implemented", "not_applicable"]
    target_architecture: str = Field(min_length=20, max_length=4000)
    risk_note: str = Field(min_length=10, max_length=4000)
    owner_label: str = Field(min_length=2, max_length=180)
    target_date: date
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)


class ArchitectureControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    baseline_id: UUID
    control_key: str
    current_state: str
    target_architecture: str
    risk_note: str
    owner_label: str
    target_date: date
    evidence_reference: str | None
    created_at: datetime
    updated_at: datetime


class ArchitectureBaselineAttest(BaseModel):
    confirm_reviewed: bool
    note: str = Field(min_length=10, max_length=4000)


class ArchitectureBaselineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pilot_execution_id: UUID
    baseline_key: str
    deployment_model: str
    data_residency_region: str
    status: str
    snapshot_hash: str | None
    attestation_note: str | None
    attested_at: datetime | None
    summary: dict
    controls: list[ArchitectureControlResponse]
    created_at: datetime


class PilotOperationsDashboard(BaseModel):
    readiness_reviews: list[ReadinessResponse]
    monitor_runs: list[MonitorRunResponse]
    incidents: list[IncidentResponse]
    governance_profile: GovernanceProfileResponse | None
    exit_manifests: list[ExitManifestResponse]
    rehearsals: list[RehearsalResponse]
    pilot_executions: list[PilotExecutionResponse]
    architecture_baselines: list[ArchitectureBaselineResponse]
