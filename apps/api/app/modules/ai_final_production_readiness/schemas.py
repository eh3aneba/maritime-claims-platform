from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AIFinalProductionReadinessCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high_coverage_outcome_assessment_id: UUID
    assessment_key: str = Field(min_length=8, max_length=120)
    confirm_recommendation_only_review: bool


class AIFinalProductionReadinessClaimEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    evidence_key: str = Field(min_length=8, max_length=120)
    workflow_type: Literal["chief_engineer_report", "engine_log"]
    baseline_tfta_seconds: int = Field(ge=1, le=604800)
    assisted_tfta_seconds: int = Field(ge=1, le=604800)
    baseline_triage_seconds: int = Field(ge=1, le=604800)
    assisted_triage_seconds: int = Field(ge=1, le=604800)
    baseline_handler_effort_seconds: int = Field(ge=1, le=604800)
    assisted_handler_effort_seconds: int = Field(ge=1, le=604800)
    baseline_rework_count: int = Field(ge=0, le=1000)
    assisted_rework_count: int = Field(ge=0, le=1000)
    handler_usefulness_rating: int = Field(ge=1, le=5)
    final_claim_decision_human_owned: bool
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_content_free_productivity_evidence: bool


class AIFinalProductionReadinessControlEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_key: Literal[
        "kill_switch_rehearsal",
        "fail_closed_no_fallback",
        "audit_traceability",
        "model_change_governance",
        "bundle_rollback_target",
        "unit_economics",
        "operations_oncall_ownership",
        "monitoring_retention_sustainability",
        "privacy_access_control",
        "data_retention_legal_basis",
    ]
    passed: bool
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_control_evidence: bool


class AIFinalProductionReadinessFinalize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_finalize: bool
    note: str = Field(min_length=10, max_length=4000)


class AIFinalProductionReadinessReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_role: Literal[
        "product", "quality", "risk", "operations", "security", "privacy",
        "claims_governance", "ai_quality",
    ]
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIFinalProductionReadinessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal[
        "recommend_separate_final_production_authorization",
        "extend_high_coverage_validation",
        "stop_ai_progression",
    ]
    confirm_recommendation_only: bool
    note: str = Field(min_length=10, max_length=4000)


class AIFinalProductionReadinessClaimEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    claim_id: UUID
    recorded_by_id: UUID | None
    evidence_key: str
    workflow_type: str
    baseline_tfta_seconds: int
    assisted_tfta_seconds: int
    baseline_triage_seconds: int
    assisted_triage_seconds: int
    baseline_handler_effort_seconds: int
    assisted_handler_effort_seconds: int
    baseline_rework_count: int
    assisted_rework_count: int
    handler_usefulness_rating: int
    final_claim_decision_human_owned: bool
    evidence_reference: str
    note: str
    evidence_hash: str
    observed_at: datetime
    created_at: datetime


class AIFinalProductionReadinessControlEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    recorded_by_id: UUID | None
    control_key: str
    passed: bool
    evidence_reference: str
    note: str
    evidence_hash: str
    observed_at: datetime
    created_at: datetime


class AIFinalProductionReadinessReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    reviewer_id: UUID | None
    review_role: str
    action: str
    evidence_reference: str | None
    note: str
    reviewed_at: datetime
    created_at: datetime


class AIFinalProductionReadinessResponse(BaseModel):
    id: UUID
    high_coverage_outcome_assessment_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    attempt_number: int
    assessment_key: str
    assessment_profile: str
    high_coverage_outcome_assessment_hash: str
    high_coverage_outcome_decision_hash: str
    inherited_hashes: dict
    bundle: dict
    rollout_percentage: int
    thresholds: dict
    status: str
    outcome: str | None
    metrics: dict | None
    failure_reasons: list[str]
    assessment_note: str | None
    assessment_hash: str | None
    assessed_at: datetime | None
    decision_note: str | None
    decision_hash: str | None
    decided_at: datetime | None
    claim_evidence: list[AIFinalProductionReadinessClaimEvidenceResponse]
    control_evidence: list[AIFinalProductionReadinessControlEvidenceResponse]
    reviews: list[AIFinalProductionReadinessReviewResponse]
    summary: dict
    created_at: datetime


class AIFinalProductionReadinessDashboard(BaseModel):
    assessments: list[AIFinalProductionReadinessResponse]
