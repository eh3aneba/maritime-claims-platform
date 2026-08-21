from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DocumentType = Literal["chief_engineer_report", "engine_log"]
ApprovalRole = Literal[
    "security", "privacy", "product", "operations", "risk", "claims_governance",
    "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
    "independent_production_assurance", "data_protection", "executive_production_sponsor",
    "enterprise_architecture_resilience", "internal_audit_model_risk",
]


class AIProductionWideCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bounded_full_outcome_assessment_id: UUID
    authorization_key: str = Field(min_length=8, max_length=120)
    allowed_document_types: list[DocumentType] = Field(min_length=1, max_length=2)
    starts_at: datetime
    expires_at: datetime
    eligibility_policy_version: str = Field(min_length=3, max_length=80)
    eligibility_policy_reference: str = Field(min_length=8, max_length=500)
    legal_basis_policy_reference: str = Field(min_length=8, max_length=500)
    data_minimization_policy_reference: str = Field(min_length=8, max_length=500)
    deployment_isolation_reference: str = Field(min_length=8, max_length=500)
    provider_project_reference: str = Field(min_length=8, max_length=500)
    credential_control_reference: str = Field(min_length=8, max_length=500)
    monitoring_reference: str = Field(min_length=8, max_length=500)
    incident_response_reference: str = Field(min_length=8, max_length=500)
    rollback_reference: str = Field(min_length=8, max_length=500)
    model_change_control_reference: str = Field(min_length=8, max_length=500)
    internal_audit_reference: str = Field(min_length=8, max_length=500)
    change_ticket_reference: str = Field(min_length=8, max_length=500)
    confirm_production_wide_human_reviewed_ai: bool

    @model_validator(mode="after")
    def validate_window(self):
        if self.expires_at <= self.starts_at:
            raise ValueError("expires_at must be after starts_at")
        if (self.expires_at - self.starts_at).total_seconds() > 90 * 86400:
            raise ValueError("Sprint 11T authorization may not exceed 90 days")
        return self


class AIProductionWideApprovalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_role: ApprovalRole
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIProductionWideDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal[
        "authorize_production_wide_human_reviewed_ai",
        "hold_for_production_remediation",
        "reject_production_wide_authorization",
    ]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AIProductionDecisionLogReview(BaseModel):
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
    confirm_different_human_review: bool


class AIProductionWideMonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monitor_key: str = Field(min_length=8, max_length=120)
    note: str = Field(min_length=10, max_length=4000)
    confirm_monitor_snapshot: bool


class AIProductionWideIncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["privacy", "security", "quality", "cost", "availability", "cross_tenant", "reliability", "other"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_pause: bool


class AIProductionWideIncidentResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_reference: str = Field(min_length=8, max_length=500)
    resolution_note: str = Field(min_length=10, max_length=4000)
    confirm_resolution: bool


class AIProductionWideLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    note: str = Field(min_length=10, max_length=4000)


class AIProductionWideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    bounded_full_outcome_assessment_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    revoked_by_id: UUID | None
    attempt_number: int
    authorization_key: str
    environment: str
    authorization_mode: str
    bounded_full_outcome_assessment_hash: str
    bounded_full_outcome_decision_hash: str
    bounded_full_decision_hash: str
    bounded_full_completion_hash: str
    model: str
    prompt_bundle_version: str
    schema_bundle_version: str
    max_input_chars: int
    max_output_tokens: int
    allowed_document_types: list[str]
    starts_at: datetime
    expires_at: datetime
    eligibility_policy_version: str
    eligibility_policy_reference: str
    legal_basis_policy_reference: str
    data_minimization_policy_reference: str
    policy_hash: str
    status: str
    outcome: str | None
    decision_note: str | None
    decision_hash: str | None
    decided_at: datetime | None
    revoked_at: datetime | None
    revocation_note: str | None
    summary: dict
    approvals: list[dict]
    eligibility_decisions: list[dict]
    decision_logs: list[dict]
    monitors: list[dict]
    incidents: list[dict]
    created_at: datetime


class AIProductionWideDashboard(BaseModel):
    authorizations: list[AIProductionWideResponse]
