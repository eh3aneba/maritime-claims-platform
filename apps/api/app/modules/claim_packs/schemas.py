from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.claim_packs.models import ClaimPackFormat


class ClaimPackGenerateRequest(BaseModel):
    export_format: ClaimPackFormat
    acknowledge_review_aid: bool
    generation_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_acknowledgement(self):
        if not self.acknowledge_review_aid:
            raise ValueError(
                "Confirm that this export is a review aid and not a coverage or settlement decision."
            )
        return self


class ClaimPackExportResponse(BaseModel):
    id: UUID
    claim_id: UUID
    export_format: ClaimPackFormat
    snapshot_schema_version: str
    snapshot_hash: str
    filename: str
    mime_type: str
    file_hash: str
    file_size_bytes: int
    generation_note: str | None
    generated_by_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimPackExportListResponse(BaseModel):
    items: list[ClaimPackExportResponse]
    total: int


class ClaimPackSnapshotSummary(BaseModel):
    approved_fact_count: int
    open_conflict_count: int
    outstanding_requirement_count: int
    open_task_count: int
    open_financial_flag_count: int
    approved_assessment_version: int | None
    assessment_is_preliminary: bool | None
    review_state: Literal["attention_required", "reviewed_with_open_items", "reviewed"]
