from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.chronology.models import ChronologyMateriality, ConflictStatus


class EventEvidenceResponse(BaseModel):
    extraction_id: UUID
    document_id: UUID
    document_name: str
    document_type: str | None
    field_path: str
    value: Any
    source_quote: str | None
    source_locator_type: str | None
    source_locator_value: str | None
    source_verified: bool
    evidence_role: str


class ChronologyEventResponse(BaseModel):
    id: UUID
    event_type: str
    title: str
    description: str | None
    occurred_on: date | None
    occurred_time: time | None
    timezone_label: str | None
    materiality: ChronologyMateriality
    evidence: list[EventEvidenceResponse]
    created_at: datetime
    updated_at: datetime


class ConflictDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    state_fingerprint: str
    state_version: int
    decision_number: int
    status: ConflictStatus
    note: str
    decided_by_id: UUID | None
    decided_at: datetime
    previous_decision_hash: str | None
    decision_hash: str
    created_at: datetime


class EvidenceConflictResponse(BaseModel):
    id: UUID
    conflict_type: str
    topic: str
    description: str
    value_a: Any
    value_b: Any
    difference_minutes: Decimal | None
    materiality: ChronologyMateriality
    state_fingerprint: str | None
    state_version: int
    decision_state: Literal["none", "current", "stale"]
    decision_history: list[ConflictDecisionResponse]
    status: ConflictStatus
    resolution_note: str | None
    event_a_id: UUID | None
    event_b_id: UUID | None
    evidence_a_extraction_id: UUID | None
    evidence_b_extraction_id: UUID | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChronologyResponse(BaseModel):
    events: list[ChronologyEventResponse]
    conflicts: list[EvidenceConflictResponse]
    event_count: int
    open_conflict_count: int


class ChronologyBuildResponse(BaseModel):
    events_created_or_activated: int
    conflicts_created_or_activated: int
    event_count: int
    open_conflict_count: int


class ConflictResolutionRequest(BaseModel):
    status: Literal["explained", "resolved", "accepted_difference", "irrelevant"]
    note: str = Field(min_length=3, max_length=3000)
    expected_state_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    expected_state_version: int | None = Field(default=None, ge=1)
    confirm_re_review: bool = False

    @model_validator(mode="after")
    def validate_expected_state_pair(self):
        supplied = self.expected_state_fingerprint is not None or self.expected_state_version is not None
        complete = self.expected_state_fingerprint is not None and self.expected_state_version is not None
        if supplied and not complete:
            raise ValueError("Conflict state fingerprint and version must be supplied together.")
        return self


class ConflictResolutionResponse(BaseModel):
    id: UUID
    status: ConflictStatus
    resolution_note: str | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    state_fingerprint: str
    state_version: int
    decision_number: int
    decision_hash: str
    replayed: bool
