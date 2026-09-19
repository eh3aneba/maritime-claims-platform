from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceProcessingReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceProcessingReleaseRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceProcessingReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    document_family_id: UUID
    document_id: UUID
    document_version_number: int
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    released_by_id: UUID
    release_reason: str
    released_at: datetime
    completion_hash: str
    revocation_request_key: str | None
    revoked_by_id: UUID | None
    revocation_reason: str | None
    revoked_at: datetime | None
    terminal_hash: str | None

    family_binding_verified: bool
    current_document_verified: bool
    local_text_processing_authorized: bool
    ai_processing_authorized: bool
    provider_io_performed: bool
    storage_io_performed: bool
    document_mutated: bool
    processing_enqueued: bool
    claim_mutated: bool

    @field_serializer("released_at", "revoked_at")
    def _utc(self, value: datetime | None):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceProcessingReleaseReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    release_id: UUID
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

    family_binding_verified: bool
    current_document_verified: bool
    local_text_processing_authorized: bool
    ai_processing_authorized: bool
    provider_io_performed: bool
    storage_io_performed: bool
    document_mutated: bool
    processing_enqueued: bool
    claim_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
