from datetime import datetime
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
