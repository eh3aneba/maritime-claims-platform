from datetime import datetime
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


class PilotOperationsDashboard(BaseModel):
    readiness_reviews: list[ReadinessResponse]
    monitor_runs: list[MonitorRunResponse]
    incidents: list[IncidentResponse]
    governance_profile: GovernanceProfileResponse | None
    exit_manifests: list[ExitManifestResponse]
    rehearsals: list[RehearsalResponse]
