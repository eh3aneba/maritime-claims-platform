from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PilotSessionStart(BaseModel):
    claim_id: UUID
    participant_role: str = Field(default="claims_handler", min_length=2, max_length=100)
    objective: str | None = Field(default=None, max_length=2000)
    baseline_assessment_minutes: int | None = Field(default=None, ge=0, le=10000)


class PilotSessionEnd(BaseModel):
    status: Literal["completed", "abandoned"] = "completed"
    note: str | None = Field(default=None, max_length=2000)


class PilotSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    participant_user_id: UUID | None
    participant_role: str
    objective: str | None
    baseline_assessment_minutes: int | None
    status: str
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime


class PilotEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=100)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    event_data: dict | None = None


class PilotFeedbackCreate(BaseModel):
    category: Literal["usability", "ai_quality", "rules", "workflow", "feature_gap", "value", "missing_document", "technical", "financial"]
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    verdict: str | None = Field(default=None, max_length=40)
    rating: int | None = Field(default=None, ge=1, le=10)
    comment: str = Field(min_length=2, max_length=5000)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: UUID | None = None


class PilotFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category: str
    severity: str
    verdict: str | None
    rating: int | None
    comment: str
    entity_type: str | None
    entity_id: UUID | None
    created_at: datetime


class PilotMetrics(BaseModel):
    session_id: UUID
    session_status: str
    elapsed_seconds: int
    baseline_assessment_minutes: int | None
    time_to_first_assessment_minutes: float | None
    estimated_time_reduction_percent: float | None
    ai_review_total: int
    ai_approved: int
    ai_edited: int
    ai_rejected: int
    ai_acceptance_rate: float | None
    ai_edit_rate: float | None
    ai_reject_rate: float | None
    feedback_count: int
    average_rating: float | None
    false_positive_count: int
    false_negative_count: int
    validated_correct_count: int
    missing_document_precision: float | None
    missing_document_recall_proxy: float | None
    friction_count: int
    tasks_completed: int
    average_task_completion_minutes: float | None
    document_requests_sent: int


class PilotBacklogItem(BaseModel):
    feedback_id: UUID
    priority: Literal["P0", "P1", "P2", "P3"]
    category: str
    title: str
    rationale: str
    entity_type: str | None
    entity_id: UUID | None


class PilotScorecard(BaseModel):
    metrics: PilotMetrics
    targets: dict[str, float]
    checks: dict[str, bool | None]
    ready_for_next_pilot: bool
    backlog: list[PilotBacklogItem]


class PilotCommercialValidationUpsert(BaseModel):
    annual_claim_volume: int | None = Field(default=None, ge=0, le=1_000_000)
    expected_users: int | None = Field(default=None, ge=0, le=100_000)
    fully_loaded_hourly_cost: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    adoption_rate: Decimal | None = Field(default=None, ge=0, le=1)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    buyer_role: str | None = Field(default=None, max_length=150)
    champion_role: str | None = Field(default=None, max_length=150)
    budget_owner_role: str | None = Field(default=None, max_length=150)
    procurement_owner_role: str | None = Field(default=None, max_length=150)
    security_approver_role: str | None = Field(default=None, max_length=150)
    budget_status: Literal["unknown", "no_budget", "exploring", "budget_identified", "approved"] = "unknown"
    buying_stage: Literal["problem_validation", "solution_evaluation", "pilot", "business_case", "procurement", "contracting", "no_interest"] = "problem_validation"
    decision_timeline_days: int | None = Field(default=None, ge=0, le=3650)

    pilot_fee_willingness: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    annual_wtp_min: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    annual_wtp_max: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    preferred_pricing_model: Literal["unknown", "pilot_fee", "annual_platform", "per_user", "per_claim", "usage"] = "unknown"

    deployment_preference: Literal["unknown", "cloud", "private_cloud", "on_prem"] = "unknown"
    value_hypotheses: list[str] = Field(default_factory=list, max_length=20)
    must_have_features: list[str] = Field(default_factory=list, max_length=50)
    required_integrations: list[str] = Field(default_factory=list, max_length=50)
    security_requirements: list[str] = Field(default_factory=list, max_length=50)
    blockers: list[str] = Field(default_factory=list, max_length=50)

    respondent_outcome: Literal["unknown", "interested", "pilot_extension", "business_case", "procurement", "no_interest"] = "unknown"
    next_step: str | None = Field(default=None, max_length=2000)
    next_step_due_date: datetime | None = None
    commercial_notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_wtp_range(self):
        if self.annual_wtp_min is not None and self.annual_wtp_max is not None and self.annual_wtp_min > self.annual_wtp_max:
            raise ValueError("annual_wtp_min cannot exceed annual_wtp_max")
        return self


class PilotCommercialValidationRead(PilotCommercialValidationUpsert):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    claim_id: UUID
    recorded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PilotROIEstimate(BaseModel):
    currency: str
    minutes_saved_per_claim: float | None
    annual_claim_volume: int | None
    adoption_rate: float | None
    annual_claims_in_scope: float | None
    annual_hours_saved: float | None
    annual_labor_value: float | None
    annual_wtp_midpoint: float | None
    estimated_roi_multiple: float | None
    estimated_payback_months: float | None
    assumptions_complete: bool
    note: str = "Pilot estimate only; not a guaranteed saving or financial forecast."


class PilotCommercialScorecard(BaseModel):
    session_id: UUID
    commercial_validation: PilotCommercialValidationRead | None
    roi: PilotROIEstimate
    checks: dict[str, bool | None]
    recommended_validation_decision: Literal["GO", "PIVOT", "STOP", "INSUFFICIENT_DATA"]
    rationale: list[str]
    next_step: str | None
