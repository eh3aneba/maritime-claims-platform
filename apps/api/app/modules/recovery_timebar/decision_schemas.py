from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


RecoveryDisposition = Literal["pursue", "monitor", "do_not_pursue", "close"]
RecoveryActionType = Literal["correspondence", "demand", "follow_up", "response", "note"]
RecoveryActionDirection = Literal["inbound", "outbound", "internal"]
RecoveryContextState = Literal["current", "stale", "reference_only", "source_unavailable"]


class RecoveryPursuitDecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterparty_id: UUID
    disposition: RecoveryDisposition
    rationale: str = Field(min_length=5, max_length=8000)
    basis_reference: str = Field(min_length=3, max_length=4000)
    next_review_date: date | None = None


class RecoveryPursuitDecisionRevisionWrite(RecoveryPursuitDecisionWrite):
    expected_decision_hash: str = Field(min_length=64, max_length=64)


class RecoveryActionLogWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_hash: str = Field(min_length=64, max_length=64)
    action_type: RecoveryActionType
    direction: RecoveryActionDirection
    occurred_on: date
    summary: str = Field(min_length=3, max_length=8000)
    source_reference: str = Field(min_length=3, max_length=4000)
    external_status: str | None = Field(default=None, min_length=2, max_length=120)
    external_response_date: date | None = None


class RecoveryActionLogResponse(BaseModel):
    id: UUID
    decision_key: UUID
    decision_id: UUID
    created_by_id: UUID | None
    action_number: int
    action_type: RecoveryActionType
    direction: RecoveryActionDirection
    occurred_on: date
    summary: str
    source_reference: str
    external_status: str | None
    external_response_date: date | None
    previous_action_hash: str | None
    action_hash: str
    created_at: datetime


class RecoveryPursuitDecisionResponse(BaseModel):
    id: UUID
    decision_key: UUID
    version: int
    supersedes_id: UUID | None
    counterparty_id: UUID
    counterparty_name: str
    counterparty_role: str
    decided_by_id: UUID | None
    disposition: RecoveryDisposition
    rationale: str
    basis_reference: str
    next_review_date: date | None
    previous_decision_hash: str | None
    decision_hash: str
    context_state_status: RecoveryContextState
    decided_at: datetime
    actions: list[RecoveryActionLogResponse]


class RecoveryDecisionDashboardResponse(BaseModel):
    claim_id: UUID
    decisions: list[RecoveryPursuitDecisionResponse]
    disclaimer: str
