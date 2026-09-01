from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecoveryTimebarDecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "edit", "dismiss", "not_applicable"]
    evaluation_hash: str = Field(min_length=64, max_length=64)
    note: str = Field(min_length=5, max_length=4000)
    edited_candidate_implication: str | None = Field(default=None, min_length=5, max_length=8000)
    edited_recommended_action: str | None = Field(default=None, min_length=5, max_length=4000)
    edited_due_date: date | None = None
    convert_to_task: bool = False

    @model_validator(mode="after")
    def validate_decision(self):
        if self.action == "edit" and not any(
            (self.edited_candidate_implication, self.edited_recommended_action, self.edited_due_date)
        ):
            raise ValueError("An edited field is required for an edit decision")
        if self.action in {"dismiss", "not_applicable"} and self.convert_to_task:
            raise ValueError("Dismissed or not-applicable evaluations cannot be converted into tasks")
        return self


class RecoveryTimebarDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    evaluation_id: UUID
    decided_by_id: UUID | None
    converted_task_id: UUID | None
    evaluation_hash: str
    decision_number: int
    action: str
    note: str
    edited_candidate_implication: str | None
    edited_recommended_action: str | None
    edited_due_date: date | None
    previous_decision_hash: str | None
    decision_hash: str
    decided_at: datetime


class RecoveryTimebarEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    snapshot_id: UUID
    evaluation_key: str
    kind: str
    status: str
    title: str
    counterparty: str | None
    candidate_basis: str | None
    trigger_date: date | None
    period_value: int | None
    period_unit: str | None
    candidate_deadline: date | None
    days_remaining: int | None
    urgency: str
    rationale: str
    candidate_implication: str
    recommended_action: str
    missing_prerequisites: list
    source_refs: list
    evaluation_hash: str
    latest_decision: RecoveryTimebarDecisionResponse | None = None


class RecoveryTimebarSnapshotResponse(BaseModel):
    id: UUID
    claim_id: UUID
    generated_by_id: UUID | None
    snapshot_version: int
    engine_version: str
    source_state_hash: str
    snapshot_hash: str
    summary: dict
    generated_at: datetime
    evaluations: list[RecoveryTimebarEvaluationResponse]


class RecoveryTimebarDashboardResponse(BaseModel):
    claim_id: UUID
    snapshot: RecoveryTimebarSnapshotResponse | None
    disclaimer: str
