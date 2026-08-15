from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.correspondence.models import CorrespondenceSensitivity
from app.modules.email_ingestion.models import EmailConnectionStatus, EmailMessageStatus


class EmailConnectionCreate(BaseModel):
    provider_label: str = Field(min_length=2, max_length=80)
    mailbox_address: EmailStr
    consent_confirmed: bool
    consent_basis: str = Field(min_length=10, max_length=4000)
    retention_days: int = Field(ge=1, le=365)


class EmailConnectionTransition(BaseModel):
    action: str
    note: str = Field(min_length=3, max_length=2000)


class EmailConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider_label: str
    mailbox_address: str
    status: EmailConnectionStatus
    consent_basis: str
    consent_confirmed_at: datetime
    retention_days: int
    last_ingested_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    ingestion_token: str | None = None


class AttachmentManifestInput(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=150)
    file_size_bytes: int = Field(ge=0, le=26214400)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class NormalizedEmailInput(BaseModel):
    provider_message_id: str = Field(min_length=1, max_length=240)
    internet_message_id: str | None = Field(default=None, max_length=500)
    sender: str = Field(min_length=3, max_length=500)
    recipients: list[str] = Field(min_length=1, max_length=50)
    cc: list[str] = Field(default_factory=list, max_length=50)
    subject: str = Field(min_length=1, max_length=500)
    body_text: str = Field(default="", max_length=50000)
    received_at: datetime
    attachments: list[AttachmentManifestInput] = Field(default_factory=list, max_length=25)


class AttachmentManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    mime_type: str
    file_size_bytes: int
    provider_sha256: str | None
    admission_status: str


class IngestedEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    connection_id: UUID
    suggested_claim_id: UUID | None
    linked_claim_id: UUID | None
    correspondence_id: UUID | None
    provider_message_id: str
    internet_message_id: str | None
    sender: str
    recipients: list
    cc: list
    subject: str
    body_text: str
    status: EmailMessageStatus
    content_hash: str
    review_note: str | None
    received_at: datetime
    retain_until: datetime
    reviewed_at: datetime | None
    created_at: datetime
    attachments: list[AttachmentManifestResponse] = Field(default_factory=list)


class EmailReview(BaseModel):
    action: str
    claim_id: UUID | None = None
    confirm_link: bool = False
    sensitivity: CorrespondenceSensitivity = CorrespondenceSensitivity.STANDARD
    note: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "link" and (not self.claim_id or not self.confirm_link):
            raise ValueError("Linking requires claim_id and explicit confirmation")
        if self.action not in {"link", "reject"}:
            raise ValueError("Action must be link or reject")
        return self


class EmailInboxResponse(BaseModel):
    connections: list[EmailConnectionResponse]
    messages: list[IngestedEmailResponse]


class ExpiryResponse(BaseModel):
    expired_count: int


class EmailAdapterCreate(BaseModel):
    connection_id: UUID
    provider_kind: Literal["microsoft_graph", "gmail_api", "provider_webhook"]
    display_name: str = Field(min_length=2, max_length=100)
    credential_reference: str = Field(min_length=3, max_length=240, pattern=r"^(env|vault|secret-manager)://")
    allowed_folder: str = Field(min_length=1, max_length=240)
    permission_manifest: list[str] = Field(min_length=1, max_length=10)
    batch_limit: int = Field(default=50, ge=1, le=100)
    retention_schedule_enabled: bool = True


class EmailAdapterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    connection_id: UUID
    provider_kind: str
    display_name: str
    credential_reference: str
    allowed_folder: str
    permission_manifest: list[str]
    status: str
    batch_limit: int
    retention_schedule_enabled: bool
    next_sync_at: datetime | None
    last_sync_at: datetime | None
    checkpoint_hash: str | None
    revoked_at: datetime | None
    created_at: datetime


class EmailAdapterRunCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    trigger: Literal["manual", "scheduled", "provider_push"] = "manual"
    messages_seen: int = Field(default=0, ge=0, le=100)
    messages_ingested: int = Field(default=0, ge=0, le=100)
    provider_checkpoint: str | None = Field(default=None, max_length=1000)
    failure_summary: str | None = Field(default=None, max_length=2000)


class EmailAdapterRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    adapter_id: UUID
    idempotency_key: str
    trigger: str
    status: str
    messages_seen: int
    messages_ingested: int
    checkpoint_hash: str | None
    failure_summary: str | None
    started_at: datetime
    finished_at: datetime | None


class RetentionRunCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)


class RetentionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    idempotency_key: str
    expired_count: int
    started_at: datetime
    finished_at: datetime


class EmailAdapterOperations(BaseModel):
    adapters: list[EmailAdapterResponse]
    runs: list[EmailAdapterRunResponse]
    retention_runs: list[RetentionRunResponse]
