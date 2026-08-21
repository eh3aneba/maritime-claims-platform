from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AIHighCoverageOutcomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high_coverage_authorization_id: UUID
    assessment_key: str = Field(min_length=8, max_length=120)
    confirm_content_free_assessment: bool


class AIHighCoverageOutcomeObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high_coverage_run_id: UUID
    usefulness_rating: int = Field(ge=1, le=5)
    review_seconds: int = Field(ge=1, le=3600)
    workflow_completed: bool
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_content_free_observation: bool


class AIHighCoverageOutcomeFinalize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_finalize: bool
    note: str = Field(min_length=10, max_length=4000)


class AIHighCoverageOutcomeReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_role: Literal[
        "product", "quality", "risk", "operations", "security",
        "claims_governance", "ai_quality",
    ]
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIHighCoverageOutcomeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal[
        "recommend_final_production_readiness_review",
        "extend_high_coverage_51_75",
        "stop_ai_progression",
    ]
    confirm_recommendation_only: bool
    note: str = Field(min_length=10, max_length=4000)


class AIHighCoverageOutcomeObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    high_coverage_run_id: UUID
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


class AIHighCoverageOutcomeReviewResponse(BaseModel):
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


class AIHighCoverageOutcomeResponse(BaseModel):
    id: UUID
    high_coverage_authorization_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    attempt_number: int
    assessment_key: str
    assessment_profile: str
    high_coverage_decision_hash: str
    high_coverage_completion_hash: str
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
    observations: list[AIHighCoverageOutcomeObservationResponse]
    reviews: list[AIHighCoverageOutcomeReviewResponse]
    summary: dict
    created_at: datetime


class AIHighCoverageOutcomeDashboard(BaseModel):
    assessments: list[AIHighCoverageOutcomeResponse]
