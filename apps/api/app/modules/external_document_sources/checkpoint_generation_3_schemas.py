from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceCheckpointGeneration3Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceCheckpointGeneration3Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    successor_versioned_restaging_execution_id: UUID
    predecessor_checkpoint_generation_execution_id: UUID
    successor_change_detection_execution_id: UUID
    versioned_restaging_execution_id: UUID
    predecessor_sync_checkpoint_execution_id: UUID
    change_detection_execution_id: UUID
    listing_execution_id: UUID
    metadata_item_id: UUID
    provider_kind: str
    profile_hash: str
    predecessor_checkpoint_generation: int
    predecessor_checkpoint_state_hash: str
    predecessor_checkpoint_completion_hash: str
    successor_change_scope_hash: str
    successor_change_request_hash: str
    successor_change_completion_hash: str
    observed_projection_hash: str
    candidate_scope_hash: str
    candidate_request_hash: str
    candidate_content_proof_hash: str
    candidate_completion_hash: str
    candidate_generation: int
    content_sha256: str
    content_byte_count: int
    media_type_class: str | None
    version_token_hash: str | None
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
    successor_checkpoint_kind: str
    successor_checkpoint_generation: int
    successor_checkpoint_state_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    result_status: str | None
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    completed_at: datetime | None
    completion_hash: str | None
    credential_reference_stored: bool
    credential_reference_resolution_performed: bool
    activation_authorization_consumed: bool
    upstream_token_acquisition_completed: bool
    upstream_provider_client_health_completed: bool
    upstream_remote_metadata_listing_completed: bool
    upstream_remote_file_content_read_completed: bool
    upstream_remote_content_staging_completed: bool
    upstream_sync_checkpoint_completed: bool
    upstream_change_detection_completed: bool
    upstream_versioned_restaging_completed: bool
    upstream_checkpoint_generation_advance_completed: bool
    upstream_successor_change_detection_completed: bool
    upstream_successor_versioned_restaging_completed: bool
    provider_client_constructed: bool
    exact_item_metadata_read_performed: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    durable_content_staged: bool
    checkpoint_created: bool
    checkpoint_advanced: bool
    checkpoint_generation_3_advance_completed: bool
    sync_executed: bool
    subscription_created: bool
    credential_stored: bool
    oauth_authorization_code_stored: bool
    access_token_stored: bool
    refresh_token_stored: bool
    id_token_stored: bool
    client_secret_stored: bool
    private_key_stored: bool
    provider_client_stored: bool
    provider_response_body_stored: bool
    remote_content_returned: bool
    remote_content_logged: bool
    content_parsed: bool
    content_extracted: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool

    @field_serializer("requested_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceCheckpointGeneration3ReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    execution_id: UUID
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
    credential_reference_resolution_performed: bool
    activation_authorization_consumed: bool
    upstream_token_acquisition_completed: bool
    upstream_provider_client_health_completed: bool
    upstream_remote_metadata_listing_completed: bool
    upstream_remote_file_content_read_completed: bool
    upstream_remote_content_staging_completed: bool
    upstream_sync_checkpoint_completed: bool
    upstream_change_detection_completed: bool
    upstream_versioned_restaging_completed: bool
    upstream_checkpoint_generation_advance_completed: bool
    upstream_successor_change_detection_completed: bool
    upstream_successor_versioned_restaging_completed: bool
    provider_client_constructed: bool
    exact_item_metadata_read_performed: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    durable_content_staged: bool
    checkpoint_created: bool
    checkpoint_advanced: bool
    checkpoint_generation_3_advance_completed: bool
    sync_executed: bool
    subscription_created: bool
    credential_stored: bool
    oauth_authorization_code_stored: bool
    access_token_stored: bool
    refresh_token_stored: bool
    id_token_stored: bool
    client_secret_stored: bool
    private_key_stored: bool
    provider_client_stored: bool
    provider_response_body_stored: bool
    remote_content_returned: bool
    remote_content_logged: bool
    content_parsed: bool
    content_extracted: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
