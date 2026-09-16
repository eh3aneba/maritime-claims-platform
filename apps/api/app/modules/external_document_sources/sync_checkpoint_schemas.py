from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSyncCheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSyncCheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    remote_content_staging_execution_id: UUID
    remote_content_read_execution_id: UUID
    listing_execution_id: UUID
    metadata_item_id: UUID
    provider_kind: str
    profile_hash: str
    metadata_item_hash: str
    staging_scope_hash: str
    staging_request_hash: str
    staging_completion_hash: str
    content_sha256: str
    content_byte_count: int
    media_type_class: str | None
    version_token_hash: str | None
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
    checkpoint_kind: str
    checkpoint_generation: int
    checkpoint_state_hash: str
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
    provider_client_constructed: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    durable_content_staged: bool
    remote_content_stored: bool
    checkpoint_created: bool
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


class ExternalDocumentSourceSyncCheckpointReceiptRead(BaseModel):
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
    provider_client_constructed: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    durable_content_staged: bool
    remote_content_stored: bool
    checkpoint_created: bool
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
