from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeverityReserveDecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "edit", "dismiss", "not_applicable"]
    evaluation_hash: str = Field(min_length=64, max_length=64)
    note: str = Field(min_length=5, max_length=4000)
    edited_severity_label: Literal["low", "medium", "high", "critical"] | None = None
    edited_lower_amount: Decimal | None = Field(default=None, ge=0)
    edited_upper_amount: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_edit(self):
        if self.action == "edit" and not any(
            value is not None
            for value in (self.edited_severity_label, self.edited_lower_amount, self.edited_upper_amount)
        ):
            raise ValueError("An edited field is required for an edit decision")
        if (
            self.edited_lower_amount is not None
            and self.edited_upper_amount is not None
            and self.edited_lower_amount > self.edited_upper_amount
        ):
            raise ValueError("Edited lower amount cannot exceed edited upper amount")
        return self


class SeverityReserveDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    evaluation_id: UUID
    decided_by_id: UUID | None
    evaluation_hash: str
    decision_number: int
    action: str
    note: str
    edited_severity_label: str | None
    edited_lower_amount: Decimal | None
    edited_upper_amount: Decimal | None
    previous_decision_hash: str | None
    decision_hash: str
    decided_at: datetime


class SeverityReserveEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    snapshot_id: UUID
    evaluation_key: str
    kind: str
    status: str
    title: str
    severity_label: str | None
    severity_score: int | None
    currency: str | None
    lower_amount: Decimal | None
    upper_amount: Decimal | None
    rationale: str
    candidate_implication: str
    recommended_action: str
    factors: list
    missing_prerequisites: list
    source_refs: list
    evaluation_hash: str
    latest_decision: SeverityReserveDecisionResponse | None = None


class SeverityReserveSnapshotResponse(BaseModel):
    id: UUID
    claim_id: UUID
    generated_by_id: UUID | None
    snapshot_version: int
    engine_version: str
    source_state_hash: str
    snapshot_hash: str
    summary: dict
    generated_at: datetime
    evaluations: list[SeverityReserveEvaluationResponse]


class SeverityReserveDashboardResponse(BaseModel):
    claim_id: UUID
    snapshot: SeverityReserveSnapshotResponse | None
    disclaimer: str
