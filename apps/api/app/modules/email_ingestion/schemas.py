from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.correspondence.models import CorrespondenceSensitivity
from app.modules.documents.models import ConfidentialityLevel
from app.modules.documents.schemas import DocumentResponse
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


class EmailAttachmentAcquisitionResponse(BaseModel):
    manifest_id: UUID
    message_id: UUID
    acquired_claim_id: UUID | None
    admission_status: str
    acquired_file_size_bytes: int | None
    acquired_file_hash: str | None
    malware_scan_status: str | None
    acquired_at: datetime | None
    malware_scanned_at: datetime | None
    acquisition_failure_code: str | None
    replayed: bool


class EmailAttachmentEvidenceAdmissionRequest(BaseModel):
    confirm_admission: bool = False
    admission_note: str = Field(min_length=20, max_length=1000)
    document_type: str | None = Field(default=None, max_length=100)
    confidentiality_level: ConfidentialityLevel = ConfidentialityLevel.CONFIDENTIAL


class EmailAttachmentEvidenceAdmissionResponse(BaseModel):
    document: DocumentResponse
    replayed: bool


class IngestedEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    connection_id: UUID
    adapter_id: UUID | None
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
    credential_backend: str
    credential_reference_configured: bool
    credential_resolver_available: bool
    credential_reference_version: int
    credential_reference_changed_at: datetime | None
    allowed_folder: str
    permission_manifest: list[str]
    status: str
    batch_limit: int
    retention_schedule_enabled: bool
    next_sync_at: datetime | None
    last_sync_at: datetime | None
    checkpoint_present: bool
    live_execution_enabled: bool
    live_execution_enabled_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class CredentialReferenceRotationRequest(BaseModel):
    confirm_rotation: bool = False
    credential_reference: str = Field(min_length=3, max_length=240, pattern=r"^(env|vault|secret-manager)://")
    reason: str = Field(min_length=20, max_length=1000)


class CredentialReferenceRotationResponse(BaseModel):
    adapter_id: UUID
    credential_backend: str
    credential_reference_version: int
    credential_reference_changed_at: datetime
    credential_resolver_available: bool
    checkpoint_preserved: bool
    next_sync_at: datetime | None
    live_execution_enabled: bool


class LiveProviderActivationRequest(BaseModel):
    confirm_activation: bool = False
    reason: str = Field(min_length=20, max_length=1000)


class LiveProviderActivationResponse(BaseModel):
    adapter_id: UUID
    provider_kind: str
    live_execution_enabled: bool
    live_execution_enabled_at: datetime
    credential_backend: str
    credential_reference_version: int
    checkpoint_present: bool
    next_sync_at: datetime


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
    checkpoint_present: bool
    checkpoint_handoff_status: str = "not_required"
    checkpoint_acknowledged_at: datetime | None = None
    checkpoint_abandoned_at: datetime | None = None
    failure_summary: str | None
    started_at: datetime
    finished_at: datetime | None


class EmailProviderExecutionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    trigger: Literal["manual", "scheduled"] = "manual"
    provider_checkpoint: str | None = Field(default=None, max_length=4000)


class EmailProviderExecutionResponse(BaseModel):
    run: EmailAdapterRunResponse
    next_checkpoint: str | None = Field(default=None, max_length=4000)
    replayed: bool
    checkpoint_handoff_required: bool = False


class CheckpointHandoffAckRequest(BaseModel):
    confirm_ack: bool = False
    provider_checkpoint: str = Field(min_length=1, max_length=4000)


class CheckpointHandoffAckResponse(BaseModel):
    adapter_id: UUID
    run_id: UUID
    checkpoint_handoff_status: str
    checkpoint_committed: bool
    next_sync_at: datetime


class CheckpointHandoffAbandonRequest(BaseModel):
    confirm_abandon: bool = False
    reason: str = Field(min_length=20, max_length=1000)


class CheckpointHandoffAbandonResponse(BaseModel):
    adapter_id: UUID
    run_id: UUID
    checkpoint_handoff_status: str
    previous_cursor_preserved: bool
    next_sync_at: datetime | None


class GmailCheckpointResetRequest(BaseModel):
    confirm_reset: bool = False


class GmailCheckpointResetResponse(BaseModel):
    adapter_id: UUID
    reset_performed: bool
    last_failure_code: str
    next_sync_at: datetime


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
