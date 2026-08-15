from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class PublishedItemInput(BaseModel):
    item_type: Literal["correspondence", "document_metadata"]
    source_id: UUID
    title: str = Field(min_length=2, max_length=240)
    summary: str | None = Field(default=None, max_length=2000)


class PortalInvitationCreate(BaseModel):
    participant_name: str = Field(min_length=2, max_length=180)
    participant_email: EmailStr
    purpose: str = Field(min_length=10, max_length=2000)
    expires_in_hours: int = Field(default=72, ge=1, le=168)
    permission_manifest: list[str] = Field(min_length=1, max_length=3)
    published_items: list[PublishedItemInput] = Field(default_factory=list, max_length=30)


class PublishedItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_type: str
    source_id: UUID
    title: str
    summary: str | None
    created_at: datetime


class PortalInvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    participant_name: str
    participant_email: str
    purpose: str
    permission_manifest: list[str]
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    invitation_token: str | None = None
    published_items: list[PublishedItemResponse] = Field(default_factory=list)


class PortalAccept(BaseModel):
    invitation_token: str = Field(min_length=32, max_length=200)


class PortalSessionResponse(BaseModel):
    session_token: str
    expires_at: datetime


class PortalAttachmentManifest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=150)
    file_size_bytes: int = Field(ge=0, le=26214400)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class PortalSubmissionCreate(BaseModel):
    subject: str = Field(min_length=2, max_length=240)
    body: str = Field(min_length=1, max_length=20000)
    attachment_manifests: list[PortalAttachmentManifest] = Field(default_factory=list, max_length=20)


class PortalSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    invitation_id: UUID
    correspondence_id: UUID | None
    subject: str
    body: str
    attachment_manifests: list
    status: str
    review_note: str | None
    submitted_at: datetime
    reviewed_at: datetime | None
    created_at: datetime


class PortalView(BaseModel):
    claim_reference: str
    vessel_name: str
    incident_date: date
    incident_description: str
    participant_name: str
    purpose: str
    permission_manifest: list[str]
    published_items: list[PublishedItemResponse]
    submissions: list[PortalSubmissionResponse]


class PortalReview(BaseModel):
    action: Literal["promote", "reject"]
    note: str = Field(min_length=3, max_length=2000)
    confirm_promotion: bool = False

    @model_validator(mode="after")
    def promotion_requires_confirmation(self):
        if self.action == "promote" and not self.confirm_promotion:
            raise ValueError("Promotion requires explicit confirmation")
        return self


class PortalRevoke(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class PortalWorkspace(BaseModel):
    invitations: list[PortalInvitationResponse]
    submissions: list[PortalSubmissionResponse]
