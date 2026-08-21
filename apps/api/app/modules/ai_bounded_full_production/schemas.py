from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["chief_engineer_report", "engine_log"]
ApprovalRole = Literal[
    "security", "privacy", "product", "operations", "risk", "claims_governance",
    "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
    "independent_production_assurance", "data_protection", "executive_production_sponsor",
]


class AIBoundedFullProductionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    near_universal_outcome_assessment_id: UUID
    authorization_key: str = Field(min_length=8, max_length=120)
    allowed_document_types: list[DocumentType] = Field(min_length=1, max_length=2)
    rollout_percentage: int = Field(ge=100, le=100)
    max_claims: int = Field(ge=1, le=120)
    max_documents: int = Field(ge=1, le=360)
    max_users: int = Field(ge=1, le=120)
    max_provider_runs: int = Field(ge=1, le=2000)
    starts_at: datetime
    expires_at: datetime
    deployment_isolation_reference: str = Field(min_length=8, max_length=500)
    provider_project_reference: str = Field(min_length=8, max_length=500)
    credential_control_reference: str = Field(min_length=8, max_length=500)
    privacy_legal_reference: str = Field(min_length=8, max_length=500)
    monitoring_reference: str = Field(min_length=8, max_length=500)
    incident_response_reference: str = Field(min_length=8, max_length=500)
    rollback_reference: str = Field(min_length=8, max_length=500)
    platform_reliability_reference: str = Field(min_length=8, max_length=500)
    data_protection_reference: str = Field(min_length=8, max_length=500)
    executive_sponsor_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    confirm_separate_bounded_full_production: bool


class AIBoundedFullProductionApprovalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_role: ApprovalRole
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIBoundedFullProductionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["authorize_bounded_100_percent_cohort", "hold_for_remediation", "reject_progression"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AIBoundedFullProductionDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    document_id: UUID
    legal_basis_reference: str = Field(min_length=8, max_length=500)
    data_minimization_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_new_bounded_full_eligibility: bool


class AIBoundedFullProductionRunOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human_review_action: Literal["approve", "edit", "reject"]
    output_candidate_count: int = Field(ge=0, le=10000)
    human_edit_count: int = Field(ge=0, le=10000)
    unsupported_output_count: int = Field(ge=0, le=10000)
    source_grounded_output_count: int = Field(ge=0, le=10000)
    source_grounding_total_count: int = Field(ge=0, le=10000)
    latency_ms: int = Field(ge=1, le=600000)
    observed_provider_cost_microusd: int = Field(ge=0, le=100000000)
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_human_review: bool


class AIBoundedFullProductionMonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monitor_key: str = Field(min_length=8, max_length=120)
    note: str = Field(min_length=10, max_length=4000)
    confirm_live_monitor_snapshot: bool


class AIBoundedFullProductionIncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["privacy", "security", "quality", "cost", "availability", "cross_tenant", "rollout", "reliability", "other"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_pause_and_rollback: bool


class AIBoundedFullProductionIncidentResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_reference: str = Field(min_length=8, max_length=500)
    resolution_note: str = Field(min_length=10, max_length=4000)
    confirm_resolution: bool


class AIBoundedFullProductionLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    note: str = Field(min_length=10, max_length=4000)


class AIBoundedFullProductionApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    authorization_id: UUID
    approver_id: UUID | None
    approval_role: str
    action: str
    evidence_reference: str | None
    note: str
    approved_at: datetime
    created_at: datetime


class AIBoundedFullProductionDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    authorization_id: UUID
    claim_id: UUID
    document_id: UUID
    attested_by_id: UUID | None
    revoked_by_id: UUID | None
    attestation_number: int
    rollout_bucket: int
    document_type: str
    confidentiality_level: str
    legal_basis_reference: str
    data_minimization_reference: str
    change_ticket_reference: str
    note: str
    snapshot_hash: str
    status: str
    attested_at: datetime
    revoked_at: datetime | None
    revocation_note: str | None
    created_at: datetime


class AIBoundedFullProductionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    authorization_id: UUID
    eligibility_id: UUID
    claim_id: UUID
    document_id: UUID
    requested_by_id: UUID | None
    reviewed_by_id: UUID | None
    run_key: str
    processing_job_id: UUID
    task_type: str
    status: str
    human_review_action: str | None
    output_candidate_count: int | None
    human_edit_count: int | None
    unsupported_output_count: int | None
    source_grounded_output_count: int | None
    source_grounding_total_count: int | None
    latency_ms: int | None
    observed_provider_cost_microusd: int | None
    evidence_reference: str | None
    note: str | None
    outcome_hash: str | None
    queued_at: datetime
    reviewed_at: datetime | None
    created_at: datetime


class AIBoundedFullProductionMonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    authorization_id: UUID
    initiated_by_id: UUID | None
    monitor_key: str
    metrics: dict
    failure_reasons: list[str]
    status: str
    monitor_hash: str
    note: str
    monitored_at: datetime
    created_at: datetime


class AIBoundedFullProductionIncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    authorization_id: UUID
    reported_by_id: UUID | None
    resolved_by_id: UUID | None
    severity: str
    category: str
    evidence_reference: str
    note: str
    status: str
    reported_at: datetime
    resolved_at: datetime | None
    resolution_reference: str | None
    resolution_note: str | None
    created_at: datetime


class AIBoundedFullProductionResponse(BaseModel):
    id: UUID
    near_universal_outcome_assessment_id: UUID
    near_universal_authorization_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    revoked_by_id: UUID | None
    attempt_number: int
    authorization_key: str
    environment: str
    authorization_mode: str
    near_universal_outcome_assessment_hash: str
    near_universal_outcome_decision_hash: str
    near_universal_decision_hash: str
    near_universal_completion_hash: str
    bundle: dict
    allowed_document_types: list[str]
    previous_rollout_percentage: int
    rollout_percentage: int
    previous_caps: dict
    max_claims: int
    max_documents: int
    max_users: int
    max_provider_runs: int
    starts_at: datetime
    expires_at: datetime
    controls: dict
    references: dict
    status: str
    outcome: str | None
    decision_note: str | None
    decision_hash: str | None
    decided_at: datetime | None
    completed_at: datetime | None
    completion_note: str | None
    completion_hash: str | None
    revoked_at: datetime | None
    revocation_note: str | None
    approvals: list[AIBoundedFullProductionApprovalResponse]
    document_eligibility: list[AIBoundedFullProductionDocumentResponse]
    runs: list[AIBoundedFullProductionRunResponse]
    monitors: list[AIBoundedFullProductionMonitorResponse]
    incidents: list[AIBoundedFullProductionIncidentResponse]
    summary: dict
    created_at: datetime


class AIBoundedFullProductionDashboard(BaseModel):
    authorizations: list[AIBoundedFullProductionResponse]
