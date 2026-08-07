from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.intelligence.models import AIRunStatus, AISemanticKind, AIReviewStatus


class AIRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    task: str
    status: AIRunStatus
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    schema_name: str
    schema_version: str
    input_char_count: int
    document_type_candidate: str | None
    classification_confidence: Decimal | None
    usage: dict | None
    warnings: list | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class DocumentExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    field_path: str
    semantic_kind: AISemanticKind
    raw_value: Any
    normalized_value: Any
    confidence: Decimal
    source_locator_type: str | None
    source_locator_value: str | None
    source_quote: str | None
    source_verified: bool
    validation_warnings: list | None
    human_status: AIReviewStatus


class DocumentIntelligenceResponse(BaseModel):
    run: AIRunResponse | None
    extractions: list[DocumentExtractionResponse]


class EngineLogEventCandidateResponse(BaseModel):
    event_index: int
    values: dict[str, Any]
    review_statuses: dict[str, str]
    source_verified: bool
    source_locators: list[dict[str, Any]]
    human_review_complete: bool
    timestamp_candidate: dict[str, Any]


class EngineLogEventsResponse(BaseModel):
    run: AIRunResponse | None
    events: list[EngineLogEventCandidateResponse]
