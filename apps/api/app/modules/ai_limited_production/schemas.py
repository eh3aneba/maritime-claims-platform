from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["chief_engineer_report", "engine_log"]


class AILimitedProductionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome_assessment_id: UUID
    authorization_key: str = Field(min_length=8, max_length=120)
    allowed_document_types: list[DocumentType] = Field(min_length=1, max_length=2)
    rollout_percentage: int = Field(ge=1, le=10)
    max_claims: int = Field(ge=1, le=10)
    max_documents: int = Field(ge=1, le=30)
    max_users: int = Field(ge=1, le=10)
    max_provider_runs: int = Field(ge=1, le=100)
    starts_at: datetime
    expires_at: datetime
    deployment_isolation_reference: str = Field(min_length=8, max_length=500)
    provider_project_reference: str = Field(min_length=8, max_length=500)
    credential_control_reference: str = Field(min_length=8, max_length=500)
    data_processing_reference: str = Field(min_length=8, max_length=500)
    monitoring_reference: str = Field(min_length=8, max_length=500)
    rollback_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    confirm_separate_limited_production_evaluation: bool


class AILimitedProductionApprovalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_role: Literal["security", "privacy", "product", "operations"]
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AILimitedProductionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["authorize_limited_evaluation", "hold"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AILimitedProductionDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    document_id: UUID
    legal_basis_reference: str = Field(min_length=8, max_length=500)
    data_minimization_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_non_restricted_rollout_document: bool


class AILimitedProductionRunOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human_review_action: Literal["approve", "edit", "reject"]
    output_candidate_count: int = Field(ge=0, le=10000)
    human_edit_count: int = Field(ge=0, le=10000)
    latency_ms: int = Field(ge=1, le=600000)
    observed_provider_cost_microusd: int = Field(ge=0, le=100000000)
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_human_review: bool


class AILimitedProductionMonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monitor_key: str = Field(min_length=8, max_length=120)
    note: str = Field(min_length=10, max_length=4000)
    confirm_live_monitor_snapshot: bool


class AILimitedProductionIncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal[
        "privacy", "security", "quality", "cost", "availability",
        "cross_tenant", "rollout", "other",
    ]
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_pause_and_rollback: bool


class AILimitedProductionIncidentResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_reference: str = Field(min_length=8, max_length=500)
    resolution_note: str = Field(min_length=10, max_length=4000)
    resume_authorization: bool = False
    confirm_resolution: bool


class AILimitedProductionResume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_resume: bool
    note: str = Field(min_length=10, max_length=4000)


class AILimitedProductionRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_revoke: bool
    note: str = Field(min_length=10, max_length=4000)


class AILimitedProductionComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_complete: bool
    note: str = Field(min_length=10, max_length=4000)


class _ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AILimitedProductionApprovalResponse(_ORMResponse):
    id: UUID; authorization_id: UUID; approver_id: UUID | None
    approval_role: str; action: str; evidence_reference: str | None
    note: str; approved_at: datetime; created_at: datetime


class AILimitedProductionDocumentResponse(_ORMResponse):
    id: UUID; authorization_id: UUID; claim_id: UUID; document_id: UUID
    attested_by_id: UUID | None; revoked_by_id: UUID | None
    attestation_number: int; rollout_bucket: int; document_type: str
    confidentiality_level: str; legal_basis_reference: str
    data_minimization_reference: str; change_ticket_reference: str
    note: str; snapshot_hash: str; status: str; attested_at: datetime
    revoked_at: datetime | None; revocation_note: str | None; created_at: datetime


class AILimitedProductionRunResponse(_ORMResponse):
    id: UUID; authorization_id: UUID; eligibility_id: UUID; claim_id: UUID
    document_id: UUID; requested_by_id: UUID | None; reviewed_by_id: UUID | None
    run_key: str; processing_job_id: UUID; task_type: str; status: str
    human_review_action: str | None; output_candidate_count: int | None
    human_edit_count: int | None; latency_ms: int | None
    observed_provider_cost_microusd: int | None; evidence_reference: str | None
    note: str | None; outcome_hash: str | None; queued_at: datetime
    reviewed_at: datetime | None; created_at: datetime


class AILimitedProductionMonitorResponse(_ORMResponse):
    id: UUID; authorization_id: UUID; initiated_by_id: UUID | None
    monitor_key: str; metrics: dict; failure_reasons: list[str]
    status: str; monitor_hash: str; note: str; monitored_at: datetime; created_at: datetime


class AILimitedProductionIncidentResponse(_ORMResponse):
    id: UUID; authorization_id: UUID; reported_by_id: UUID | None
    resolved_by_id: UUID | None; severity: str; category: str
    evidence_reference: str; note: str; status: str; reported_at: datetime
    resolved_at: datetime | None; resolution_reference: str | None
    resolution_note: str | None; created_at: datetime


class AILimitedProductionResponse(BaseModel):
    id: UUID; outcome_assessment_id: UUID; pilot_id: UUID; evaluation_suite_id: UUID
    requested_by_id: UUID | None; finalized_by_id: UUID | None; revoked_by_id: UUID | None
    attempt_number: int; authorization_key: str; environment: str; evaluation_mode: str
    model: str; prompt_bundle_version: str; schema_bundle_version: str
    max_input_chars: int; max_output_tokens: int; allowed_document_types: list[str]
    rollout_percentage: int; max_claims: int; max_documents: int
    max_users: int; max_provider_runs: int; starts_at: datetime; expires_at: datetime
    controls: dict; references: dict; status: str; outcome: str | None
    decision_note: str | None; decision_hash: str | None; decided_at: datetime | None
    completed_at: datetime | None; completion_note: str | None
    revoked_at: datetime | None; revocation_note: str | None
    approvals: list[AILimitedProductionApprovalResponse]
    document_eligibility: list[AILimitedProductionDocumentResponse]
    runs: list[AILimitedProductionRunResponse]
    monitors: list[AILimitedProductionMonitorResponse]
    incidents: list[AILimitedProductionIncidentResponse]
    summary: dict; created_at: datetime


class AILimitedProductionDashboard(BaseModel):
    authorizations: list[AILimitedProductionResponse]
