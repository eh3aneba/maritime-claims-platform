from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.correspondence.models import (
    CorrespondenceChannel,
    CorrespondenceDirection,
    CorrespondenceKind,
    CorrespondenceSensitivity,
    CorrespondenceStatus,
)


class CorrespondenceCreate(BaseModel):
    direction: CorrespondenceDirection = CorrespondenceDirection.OUTBOUND
    kind: CorrespondenceKind = CorrespondenceKind.GENERAL
    sensitivity: CorrespondenceSensitivity = CorrespondenceSensitivity.STANDARD
    sender_label: str | None = Field(default=None, max_length=180)
    recipient_label: str | None = Field(default=None, max_length=180)
    subject: str = Field(min_length=3, max_length=240)
    body: str = Field(min_length=3, max_length=50000)
    channel: CorrespondenceChannel | None = None
    external_reference: str | None = Field(default=None, max_length=240)
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def validate_direction_fields(self):
        if self.direction == CorrespondenceDirection.OUTBOUND and not (self.recipient_label or "").strip():
            raise ValueError("Outbound correspondence requires a recipient label")
        if self.direction == CorrespondenceDirection.INBOUND and not (self.sender_label or "").strip():
            raise ValueError("Inbound correspondence requires a sender label")
        return self


class CorrespondenceUpdate(BaseModel):
    kind: CorrespondenceKind | None = None
    sensitivity: CorrespondenceSensitivity | None = None
    sender_label: str | None = Field(default=None, max_length=180)
    recipient_label: str | None = Field(default=None, max_length=180)
    subject: str | None = Field(default=None, min_length=3, max_length=240)
    body: str | None = Field(default=None, min_length=3, max_length=50000)


class CorrespondenceReview(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class CorrespondenceMarkSent(BaseModel):
    confirm_sent: bool
    channel: CorrespondenceChannel
    external_reference: str | None = Field(default=None, max_length=240)
    sent_at: datetime | None = None


class CorrespondenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    request_batch_id: UUID | None
    created_by_id: UUID | None
    reviewed_by_id: UUID | None
    sent_by_id: UUID | None
    direction: CorrespondenceDirection
    kind: CorrespondenceKind
    status: CorrespondenceStatus
    sensitivity: CorrespondenceSensitivity
    channel: CorrespondenceChannel | None
    sender_label: str | None
    recipient_label: str | None
    subject: str
    body: str
    requirement_ids: list
    review_note: str | None
    external_reference: str | None
    content_hash: str | None
    occurred_at: datetime | None
    reviewed_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CorrespondenceListResponse(BaseModel):
    items: list[CorrespondenceResponse]
    total: int
