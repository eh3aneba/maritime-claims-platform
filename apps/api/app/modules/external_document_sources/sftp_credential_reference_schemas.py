from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpCredentialReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)
    authentication_kind: str = Field(min_length=1, max_length=32)
    reference_backend: str = Field(min_length=1, max_length=32)
    reference_namespace: str = Field(min_length=1, max_length=128)
    reference_name: str = Field(min_length=1, max_length=128)
    reference_version: str | None = Field(default=None, min_length=1, max_length=64)


class ExternalDocumentSourceSftpCredentialReferenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpCredentialReferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    provider_kind: str
    profile_hash: str
    authentication_kind: str
    reference_backend: str
    reference_namespace: str
    reference_name: str
    reference_version: str | None
    locator_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    approval_hash: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    terminal_hash: str | None
    credential_reference_stored: bool
    credential_stored: bool
    secret_resolution_performed: bool
    provider_network_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    evidence_admitted: bool
    document_created: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool

    @field_serializer("requested_at", "approved_at", "terminal_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpCredentialReferenceReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    binding_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    scope_hash: str
    decision_hash: str
    prior_receipt_hash: str | None
    receipt_hash: str
    credential_reference_stored: bool
    credential_stored: bool
    secret_resolution_performed: bool
    provider_network_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    evidence_admitted: bool
    document_created: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
