from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceRecurringBaselineTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=1000)


class ExternalDocumentSourceRecurringBaselineTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    document_family_id: UUID
    schedule_id: UUID
    schedule_revision_number: int

    refresh_admission_execution_id: UUID
    refresh_execution_id: UUID
    originating_observation_execution_id: UUID
    prior_document_id: UUID
    current_document_id: UUID
    current_version_number: int

    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    binding_completion_hash: str
    schedule_authorization_hash: str
    refresh_admission_completion_hash: str
    refresh_completion_hash: str
    originating_observation_completion_hash: str

    baseline_projection_hash: str
    baseline_version_token_hash: str | None
    refreshed_content_sha256: str
    refreshed_content_proof_hash: str

    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    authorized_by_id: UUID
    authorization_reason: str
    authorized_at: datetime
    completion_hash: str

    refresh_admission_verified: bool
    refresh_execution_verified: bool
    originating_observation_verified: bool
    family_binding_verified: bool
    stable_source_identity_verified: bool
    current_document_verified: bool
    schedule_authority_verified: bool
    human_authorization_recorded: bool
    recurring_baseline_established: bool

    provider_client_constructed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    document_mutated: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_mutated: bool
    schedule_mutated: bool

    @field_serializer("authorized_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceRecurringBaselineTransitionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    transition_id: UUID
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

    refresh_admission_verified: bool
    refresh_execution_verified: bool
    originating_observation_verified: bool
    family_binding_verified: bool
    stable_source_identity_verified: bool
    current_document_verified: bool
    schedule_authority_verified: bool
    human_authorization_recorded: bool
    recurring_baseline_established: bool

    provider_client_constructed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    document_mutated: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_mutated: bool
    schedule_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
