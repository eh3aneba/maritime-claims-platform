from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReviewRole = Literal[
    "product", "quality", "risk", "operations", "security", "privacy",
    "claims_governance", "ai_quality", "legal_data_governance", "business_owner",
    "platform_reliability", "independent_production_assurance",
]
WorkflowType = Literal["chief_engineer_report", "engine_log"]


class AINearUniversalOutcomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    near_universal_authorization_id: UUID
    assessment_key: str = Field(min_length=8, max_length=120)
    confirm_content_free_assessment: bool


class AINearUniversalOutcomeObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    near_universal_run_id: UUID
    usefulness_rating: int = Field(ge=1, le=5)
    review_seconds: int = Field(ge=1, le=3600)
    workflow_completed: bool
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_content_free_observation: bool


class AINearUniversalOutcomeBusinessCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    evidence_key: str = Field(min_length=8, max_length=120)
    workflow_type: WorkflowType
    baseline_tfta_seconds: int = Field(ge=1, le=864000)
    assisted_tfta_seconds: int = Field(ge=1, le=864000)
    baseline_triage_seconds: int = Field(ge=1, le=864000)
    assisted_triage_seconds: int = Field(ge=1, le=864000)
    baseline_handler_effort_seconds: int = Field(ge=1, le=864000)
    assisted_handler_effort_seconds: int = Field(ge=1, le=864000)
    baseline_rework_count: int = Field(ge=0, le=10000)
    assisted_rework_count: int = Field(ge=0, le=10000)
    baseline_escalation_count: int = Field(ge=0, le=10000)
    assisted_escalation_count: int = Field(ge=0, le=10000)
    baseline_correction_count: int = Field(ge=0, le=10000)
    assisted_correction_count: int = Field(ge=0, le=10000)
    handler_usefulness_rating: int = Field(ge=1, le=5)
    final_claim_decision_human_owned: bool
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_content_free_business_evidence: bool


class AINearUniversalOutcomeFinalize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_finalize: bool
    note: str = Field(min_length=10, max_length=4000)


class AINearUniversalOutcomeReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_role: ReviewRole
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AINearUniversalOutcomeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal[
        "recommend_separate_100_percent_authorization_review",
        "extend_near_universal_91_99",
        "stop_ai_progression",
    ]
    confirm_recommendation_only: bool
    note: str = Field(min_length=10, max_length=4000)


class AINearUniversalOutcomeObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    near_universal_run_id: UUID
    observed_by_id: UUID | None
    workflow_type: str
    usefulness_rating: int
    review_seconds: int
    workflow_completed: bool
    evidence_reference: str
    note: str
    observation_hash: str
    observed_at: datetime
    created_at: datetime


class AINearUniversalOutcomeBusinessResponse(BaseModel):
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
    baseline_escalation_count: int
    assisted_escalation_count: int
    baseline_correction_count: int
    assisted_correction_count: int
    handler_usefulness_rating: int
    final_claim_decision_human_owned: bool
    evidence_reference: str
    note: str
    evidence_hash: str
    observed_at: datetime
    created_at: datetime


class AINearUniversalOutcomeReviewResponse(BaseModel):
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


class AINearUniversalOutcomeResponse(BaseModel):
    id: UUID
    near_universal_authorization_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    attempt_number: int
    assessment_key: str
    assessment_profile: str
    near_universal_decision_hash: str
    near_universal_completion_hash: str
    inherited_hashes: dict
    bundle: dict
    allowed_document_types: list[str]
    rollout_percentage: int
    authorization_caps: dict
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
    observations: list[AINearUniversalOutcomeObservationResponse]
    business_evidence: list[AINearUniversalOutcomeBusinessResponse]
    reviews: list[AINearUniversalOutcomeReviewResponse]
    summary: dict
    created_at: datetime


class AINearUniversalOutcomeDashboard(BaseModel):
    assessments: list[AINearUniversalOutcomeResponse]
