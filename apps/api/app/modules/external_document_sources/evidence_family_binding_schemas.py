from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceEvidenceFamilyBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceEvidenceFamilyBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    admission_execution_id: UUID
    initial_document_id: UUID
    document_family_id: UUID
    current_document_id: UUID
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    source_projection_hash: str
    source_observation_completion_hash: str
    admission_completion_hash: str
    current_version_number: int
    admitted_content_sha256: str
    admitted_byte_count: int
    admitted_mime_type_class: str | None
    admitted_provider_version_hash: str | None
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    bound_by_id: UUID
    binding_reason: str
    bound_at: datetime
    completion_hash: str

    upstream_admission_verified: bool
    stable_source_identity_derived: bool
    document_family_verified: bool
    version_baseline_recorded: bool
    provider_client_constructed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_created: bool
    document_mutated: bool
    processing_enqueued: bool
    content_extracted: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_sync_started: bool

    @field_serializer("bound_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceEvidenceFamilyBindingReceiptRead(BaseModel):
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

    upstream_admission_verified: bool
    stable_source_identity_derived: bool
    document_family_verified: bool
    version_baseline_recorded: bool
    provider_client_constructed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_created: bool
    document_mutated: bool
    processing_enqueued: bool
    content_extracted: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_sync_started: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
