from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["chief_engineer_report", "engine_log"]
ApprovalRole = Literal[
    "security", "privacy", "product", "operations", "risk",
    "claims_governance", "ai_quality", "legal_data_governance", "business_owner",
]


class AIFinalProductionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readiness_assessment_id: UUID
    authorization_key: str = Field(min_length=8, max_length=120)
    allowed_document_types: list[DocumentType] = Field(min_length=1, max_length=2)
    rollout_percentage: int = Field(ge=76, le=90)
    max_claims: int = Field(ge=1, le=100)
    max_documents: int = Field(ge=1, le=300)
    max_users: int = Field(ge=1, le=100)
    max_provider_runs: int = Field(ge=1, le=1500)
    starts_at: datetime
    expires_at: datetime
    deployment_isolation_reference: str = Field(min_length=8, max_length=500)
    provider_project_reference: str = Field(min_length=8, max_length=500)
    credential_control_reference: str = Field(min_length=8, max_length=500)
    privacy_legal_reference: str = Field(min_length=8, max_length=500)
    monitoring_reference: str = Field(min_length=8, max_length=500)
    incident_response_reference: str = Field(min_length=8, max_length=500)
    rollback_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    confirm_separate_final_production: bool


class AIFinalProductionApprovalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_role: ApprovalRole
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIFinalProductionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["authorize_final_production_cohort", "hold_for_remediation", "reject_progression"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AIFinalProductionDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    document_id: UUID
    legal_basis_reference: str = Field(min_length=8, max_length=500)
    data_minimization_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_new_final_production_eligibility: bool


class AIFinalProductionRunOutcome(BaseModel):
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


class AIFinalProductionMonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monitor_key: str = Field(min_length=8, max_length=120)
    note: str = Field(min_length=10, max_length=4000)
    confirm_live_monitor_snapshot: bool


class AIFinalProductionIncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["privacy", "security", "quality", "cost", "availability", "cross_tenant", "rollout", "other"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_pause_and_rollback: bool


class AIFinalProductionIncidentResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_reference: str = Field(min_length=8, max_length=500)
    resolution_note: str = Field(min_length=10, max_length=4000)
    confirm_resolution: bool


class AIFinalProductionLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    note: str = Field(min_length=10, max_length=4000)


class _ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AIFinalProductionApprovalResponse(_ORMResponse):
    id: UUID
    authorization_id: UUID
    approver_id: UUID | None
    approval_role: str
    action: str
    evidence_reference: str | None
    note: str
    approved_at: datetime
    created_at: datetime


class AIFinalProductionDocumentResponse(_ORMResponse):
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


class AIFinalProductionRunResponse(_ORMResponse):
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


class AIFinalProductionMonitorResponse(_ORMResponse):
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


class AIFinalProductionIncidentResponse(_ORMResponse):
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


class AIFinalProductionResponse(BaseModel):
    id: UUID
    readiness_assessment_id: UUID
    high_coverage_outcome_assessment_id: UUID
    high_coverage_authorization_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    revoked_by_id: UUID | None
    attempt_number: int
    authorization_key: str
    environment: str
    authorization_mode: str
    readiness_assessment_hash: str
    readiness_decision_hash: str
    inherited_hashes: dict
    bundle: dict
    allowed_document_types: list[str]
    previous_rollout_percentage: int
    rollout_percentage: int
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
    approvals: list[AIFinalProductionApprovalResponse]
    document_eligibility: list[AIFinalProductionDocumentResponse]
    runs: list[AIFinalProductionRunResponse]
    monitors: list[AIFinalProductionMonitorResponse]
    incidents: list[AIFinalProductionIncidentResponse]
    summary: dict
    created_at: datetime


class AIFinalProductionDashboard(BaseModel):
    authorizations: list[AIFinalProductionResponse]
