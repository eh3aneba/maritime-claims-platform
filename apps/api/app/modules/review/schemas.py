from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.intelligence.models import AISemanticKind, AIReviewStatus


class ReviewQueueItem(BaseModel):
    extraction_id: UUID
    claim_id: UUID
    claim_reference: str
    vessel_name: str
    document_id: UUID
    document_name: str
    field_path: str
    semantic_kind: AISemanticKind
    ai_value: Any
    normalized_value: Any
    confidence: Decimal
    source_locator_type: str | None
    source_locator_value: str | None
    source_quote: str | None
    source_verified: bool
    validation_warnings: list | None
    human_status: AIReviewStatus
    approved_value: Any
    reviewed_at: datetime | None
    bulk_approvable: bool
    created_at: datetime


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    limit: int
    offset: int


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    value: Any | None = None
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_action_payload(self):
        if self.action == "edit" and self.value is None:
            raise ValueError("Edited reviews require a replacement value.")
        if self.action == "reject" and self.value is not None:
            raise ValueError("Rejected reviews must not include an approved value.")
        return self


class ClaimFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    field_path: str
    value: Any
    source_extraction_id: UUID
    source_document_id: UUID
    source_segment_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime
    version: int


class ReviewResult(BaseModel):
    extraction_id: UUID
    human_status: AIReviewStatus
    approved_value: Any
    promoted: bool
    claim_fact: ClaimFactResponse | None


class BulkApproveRequest(BaseModel):
    extraction_ids: list[UUID] = Field(min_length=1, max_length=50)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def unique_extraction_ids(self):
        if len(set(self.extraction_ids)) != len(self.extraction_ids):
            raise ValueError("Bulk approval cannot contain duplicate extraction IDs.")
        return self


class BulkApproveResponse(BaseModel):
    reviewed: list[ReviewResult]


class SourcePreviewResponse(BaseModel):
    extraction_id: UUID
    claim_id: UUID
    document_id: UUID
    document_name: str
    field_path: str
    source_locator_type: str | None
    source_locator_value: str | None
    source_quote: str | None
    source_verified: bool
    segment_id: UUID | None
    segment_text: str | None


class FeedbackResponse(BaseModel):
    id: UUID
    action: str
    ai_value: Any
    human_value: Any
    reason: str | None
    reviewer_id: UUID | None
    reviewer_name: str | None
    reviewer_email: str | None
    created_at: datetime


class ExtractionReviewDetail(BaseModel):
    item: ReviewQueueItem
    feedback: list[FeedbackResponse]
    current_claim_fact: ClaimFactResponse | None
