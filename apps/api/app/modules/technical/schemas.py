from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


TechnicalDecisionAction = Literal[
    "keep_open",
    "supported_for_investigation",
    "not_supported",
    "needs_more_evidence",
]
TechnicalDecisionState = Literal["none", "current", "stale"]


class TechnicalEvidenceItem(BaseModel):
    extraction_id: UUID | None = None
    field_path: str
    value: Any
    document_id: UUID | None = None
    source_quote: str | None = None
    source_locator_type: str | None = None
    source_locator_value: str | None = None
    source_verified: bool | None = None


class TechnicalInvestigationDecisionResponse(BaseModel):
    id: UUID
    topic_key: str
    topic_kind: str
    state_fingerprint: str
    state_version: int
    decision_number: int
    action: TechnicalDecisionAction
    note: str
    decided_by_id: UUID | None = None
    decided_at: datetime
    previous_decision_hash: str | None = None
    decision_hash: str

    model_config = {"from_attributes": True}


class TechnicalDecisionCreate(BaseModel):
    action: TechnicalDecisionAction
    note: str = Field(min_length=5, max_length=4000)
    expected_state_fingerprint: str = Field(min_length=64, max_length=64)
    expected_state_version: int = Field(ge=1)
    confirm_re_review: bool = False


class TechnicalDecisionHistoryResponse(BaseModel):
    topic_key: str
    current_state_fingerprint: str | None = None
    current_state_version: int | None = None
    decision_state: TechnicalDecisionState
    items: list[TechnicalInvestigationDecisionResponse]


class TechnicalMatrixRow(BaseModel):
    key: str
    topic_kind: str
    title: str
    severity: str
    status: str
    evidence_for: list[Any]
    evidence_against: list[Any]
    unknown_or_missing: list[str]
    recommended_follow_up: list[str]
    explanation: str
    state_fingerprint: str
    state_version: int
    decision_state: TechnicalDecisionState
    latest_decision: TechnicalInvestigationDecisionResponse | None = None


class TechnicalReviewResponse(BaseModel):
    maintenance_facts: dict[str, Any]
    workshop_findings: list[TechnicalEvidenceItem]
    workshop_repair_options: list[TechnicalEvidenceItem]
    workshop_cause_opinions: list[TechnicalEvidenceItem]
    matrix: list[TechnicalMatrixRow]
    generated_at: datetime