from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.assessments.models import AssessmentSectionStatus, AssessmentStatus


AssessmentSourceState = Literal["current", "stale", "legacy_unbound"]


class AssessmentGenerateRequest(BaseModel):
    allow_if_not_ready: bool = False
    override_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_override(self):
        if self.allow_if_not_ready and (not self.override_reason or len(self.override_reason.strip()) < 3):
            raise ValueError("override_reason is required when allow_if_not_ready=true")
        return self


class AssessmentSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    section_key: str
    title: str
    sort_order: int
    draft_text: str
    approved_text: str | None
    status: AssessmentSectionStatus
    source_manifest: list
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None


class AssessmentRead(BaseModel):
    id: UUID
    claim_id: UUID
    version: int
    status: AssessmentStatus
    readiness_score: int
    readiness_state: str
    blocking_items: list
    is_preliminary: bool
    generation_override_reason: str | None
    generated_by_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    source_fingerprint: str | None
    current_source_fingerprint: str | None
    source_state: AssessmentSourceState
    approved_content_hash: str | None
    created_at: datetime
    updated_at: datetime
    sections: list[AssessmentSectionRead]


class AssessmentSectionReview(BaseModel):
    action: Literal["approve", "edit"]
    text: str | None = Field(default=None, max_length=20000)
    expected_source_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_text_for_edit(self):
        if self.action == "edit" and (not self.text or not self.text.strip()):
            raise ValueError("text is required for edit")
        return self


class AssessmentApproveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    expected_source_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
