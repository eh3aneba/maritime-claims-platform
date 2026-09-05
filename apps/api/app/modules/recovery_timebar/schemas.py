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
    evaluation_date: date
    source_state_hash: str
    snapshot_hash: str
    summary: dict
    generated_at: datetime
    evaluations: list[RecoveryTimebarEvaluationResponse]


class RecoveryTimebarDashboardResponse(BaseModel):
    claim_id: UUID
    snapshot: RecoveryTimebarSnapshotResponse | None
    disclaimer: str


PeriodUnit = Literal["days", "months", "years"]
ScenarioReviewAction = Literal["confirm", "override", "reject", "review_needed"]


class RecoveryCounterpartyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=240)
    role: str = Field(min_length=2, max_length=120)
    allegation_basis: str = Field(min_length=5, max_length=8000)
    source_reference: str = Field(min_length=3, max_length=4000)
    source_document_id: UUID | None = None


class RecoveryCounterpartyRevisionWrite(RecoveryCounterpartyWrite):
    expected_record_hash: str = Field(min_length=64, max_length=64)


class RecoveryCounterpartyResponse(BaseModel):
    id: UUID
    counterparty_key: UUID
    version: int
    supersedes_id: UUID | None
    created_by_id: UUID | None
    name: str
    role: str
    allegation_basis: str
    source_reference: str
    source_document_id: UUID | None
    source_document_family_id: UUID | None
    source_document_version: int | None
    source_document_hash: str | None
    source_state_status: Literal["current", "stale", "reference_only", "source_unavailable"]
    record_hash: str
    created_at: datetime


class TimebarScenarioWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=220)
    legal_basis: str = Field(min_length=5, max_length=8000)
    source_reference: str = Field(min_length=3, max_length=4000)
    source_document_id: UUID | None = None
    counterparty_id: UUID | None = None
    anchor_date: date
    period_value: int = Field(gt=0, le=10000)
    period_unit: PeriodUnit
    extension_value: int | None = Field(default=None, ge=0, le=10000)
    extension_unit: PeriodUnit | None = None
    extension_basis: str | None = Field(default=None, min_length=5, max_length=4000)
    assumptions: str = Field(min_length=5, max_length=8000)

    @model_validator(mode="after")
    def validate_extension(self):
        if self.extension_value is None:
            if self.extension_unit is not None or self.extension_basis is not None:
                raise ValueError("Extension unit/basis requires an explicit extension value")
            return self
        if self.extension_unit is None:
            raise ValueError("Extension unit is required when an extension value is supplied")
        if self.extension_value > 0 and not self.extension_basis:
            raise ValueError("Extension/tolling basis is required for a positive extension assumption")
        return self


class TimebarScenarioRevisionWrite(TimebarScenarioWrite):
    expected_scenario_hash: str = Field(min_length=64, max_length=64)


class TimebarScenarioReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ScenarioReviewAction
    scenario_hash: str = Field(min_length=64, max_length=64)
    confirmed_deadline: date | None = None
    note: str = Field(min_length=5, max_length=4000)
    source_reference: str | None = Field(default=None, min_length=3, max_length=4000)

    @model_validator(mode="after")
    def validate_review(self):
        if self.action == "confirm" and self.confirmed_deadline is not None:
            raise ValueError("Confirm uses the immutable candidate deadline; use override for a different human deadline")
        if self.action == "override":
            if self.confirmed_deadline is None:
                raise ValueError("Override requires an explicit human-confirmed deadline")
            if not self.source_reference:
                raise ValueError("Override requires a source reference")
        if self.action in {"reject", "review_needed"} and self.confirmed_deadline is not None:
            raise ValueError("Rejected/review-needed scenarios cannot set a confirmed deadline")
        return self


class TimebarScenarioReviewResponse(BaseModel):
    id: UUID
    scenario_id: UUID
    reviewed_by_id: UUID | None
    scenario_hash: str
    review_number: int
    action: ScenarioReviewAction
    confirmed_deadline: date | None
    note: str
    source_reference: str | None
    previous_review_hash: str | None
    review_hash: str
    reviewed_at: datetime


class TimebarScenarioResponse(BaseModel):
    id: UUID
    scenario_key: UUID
    version: int
    supersedes_id: UUID | None
    created_by_id: UUID | None
    counterparty_id: UUID | None
    title: str
    legal_basis: str
    source_reference: str
    source_document_id: UUID | None
    source_document_family_id: UUID | None
    source_document_version: int | None
    source_document_hash: str | None
    source_state_status: Literal["current", "stale", "reference_only", "source_unavailable"]
    anchor_date: date
    period_value: int
    period_unit: PeriodUnit
    extension_value: int | None
    extension_unit: PeriodUnit | None
    extension_basis: str | None
    assumptions: str
    candidate_deadline: date
    scenario_hash: str
    created_at: datetime
    latest_review: TimebarScenarioReviewResponse | None = None


class RecoveryMaturityDashboardResponse(BaseModel):
    claim_id: UUID
    counterparties: list[RecoveryCounterpartyResponse]
    scenarios: list[TimebarScenarioResponse]
    disclaimer: str
