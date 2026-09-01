from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClaimIntelligenceDecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "edit", "dismiss"]
    note: str = Field(min_length=5, max_length=4000)
    edited_title: str | None = Field(default=None, min_length=3, max_length=240)
    edited_description: str | None = Field(default=None, min_length=5, max_length=8000)
    edited_suggested_action: str | None = Field(default=None, min_length=5, max_length=4000)
    convert_to_task: bool = False

    @model_validator(mode="after")
    def validate_edit(self):
        if self.action == "edit" and not any((self.edited_title, self.edited_description, self.edited_suggested_action)):
            raise ValueError("An edited field is required for an edit decision")
        if self.action == "dismiss" and self.convert_to_task:
            raise ValueError("Dismissed intelligence cannot be converted into a task")
        return self


class ClaimIntelligenceDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    decided_by_id: UUID | None
    converted_task_id: UUID | None
    decision_number: int
    action: str
    edited_title: str | None
    edited_description: str | None
    edited_suggested_action: str | None
    note: str
    previous_decision_hash: str | None
    decision_hash: str
    decided_at: datetime


class ClaimIntelligenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    snapshot_id: UUID
    item_key: str
    category: str
    title: str
    description: str
    severity: str
    urgency_score: int
    evidential_value_score: int
    rank_score: int
    rationale: str
    source_refs: list[dict]
    action_type: str | None
    suggested_action: str | None
    related_entity_type: str | None
    related_entity_id: UUID | None
    item_hash: str
    latest_decision: ClaimIntelligenceDecisionResponse | None = None


class ClaimIntelligenceSnapshotResponse(BaseModel):
    id: UUID
    claim_id: UUID
    generated_by_id: UUID | None
    snapshot_version: int
    engine_version: str
    source_state_hash: str
    snapshot_hash: str
    summary: dict
    generated_at: datetime
    items: list[ClaimIntelligenceItemResponse]


class ClaimIntelligenceDashboardResponse(BaseModel):
    claim_id: UUID
    snapshot: ClaimIntelligenceSnapshotResponse | None
    disclaimer: str
