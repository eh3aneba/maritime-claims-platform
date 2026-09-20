from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceDueTickObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceDueTickObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    schedule_id: UUID
    binding_id: UUID
    document_family_id: UUID
    current_document_id: UUID
    current_version_number: int
    provider_lineage_observation_id: UUID
    provider_lineage_checkpoint_id: UUID
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    binding_completion_hash: str
    schedule_authorization_hash: str
    schedule_revision_number: int
    cadence_class: str
    cadence_minutes: int
    due_at: datetime
    baseline_projection_hash: str
    baseline_version_token_hash: str | None
    observation_operation_kind: str
    observation_adapter_kind: str
    endpoint_policy_hash: str
    result_status: str
    observed_projection_hash: str | None
    observed_display_name_hash: str | None
    observed_version_token_hash: str | None
    observed_byte_size: int | None
    observed_modified_at: datetime | None
    observed_mime_type_class: str | None
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    actor_kind: str
    executed_by_id: UUID | None
    service_executor_id_hash: str | None
    execution_reason: str
    executed_at: datetime
    completed_at: datetime
    completion_hash: str

    schedule_authority_verified: bool
    family_binding_verified: bool
    current_document_verified: bool
    provider_lineage_verified: bool
    due_tick_verified: bool
    provider_client_constructed: bool
    exact_item_metadata_read_performed: bool
    remote_list_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_mutated: bool
    evidence_admitted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_worker_started: bool

    @field_serializer("due_at", "observed_modified_at", "executed_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceDueTickObservationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    execution_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_kind: str
    actor_id: UUID | None
    service_executor_id_hash: str | None
    occurred_at: datetime
    reason: str
    scope_hash: str
    decision_hash: str
    prior_receipt_hash: str | None
    receipt_hash: str

    schedule_authority_verified: bool
    family_binding_verified: bool
    current_document_verified: bool
    provider_lineage_verified: bool
    due_tick_verified: bool
    provider_client_constructed: bool
    exact_item_metadata_read_performed: bool
    remote_list_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_mutated: bool
    evidence_admitted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_worker_started: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
