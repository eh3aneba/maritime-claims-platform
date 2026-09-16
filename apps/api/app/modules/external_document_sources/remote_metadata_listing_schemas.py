from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceRemoteMetadataListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceRemoteMetadataListingItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    execution_id: UUID
    item_index: int
    provider_item_id: str
    parent_item_id: str | None
    item_kind: str
    display_name: str
    mime_type_class: str | None
    byte_size: int | None
    modified_at: datetime | None
    version_token_hash: str | None
    item_hash: str

    @field_serializer("modified_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceRemoteMetadataListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    provider_client_health_execution_id: UUID
    token_acquisition_execution_id: UUID
    credential_resolution_execution_id: UUID
    credential_reference_binding_id: UUID
    provider_kind: str
    profile_hash: str
    locator_hash: str
    reference_backend: str
    resolution_resolver_kind: str
    token_flow_kind: str
    client_kind: str
    health_operation_kind: str
    health_adapter_kind: str
    provider_client_health_scope_hash: str
    provider_client_health_request_hash: str
    provider_client_health_completion_hash: str
    listing_operation_kind: str
    list_adapter_kind: str
    endpoint_policy_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    result_status: str | None
    item_count: int
    page_count: int
    truncated: bool
    items_hash: str | None
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
    provider_client_constructed: bool
    remote_list_performed: bool
    credential_stored: bool
    oauth_authorization_code_stored: bool
    access_token_stored: bool
    refresh_token_stored: bool
    id_token_stored: bool
    client_secret_stored: bool
    private_key_stored: bool
    provider_client_stored: bool
    provider_response_body_stored: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    checkpoint_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    items: list[ExternalDocumentSourceRemoteMetadataListingItemRead] = Field(default_factory=list)

    @field_serializer("requested_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceRemoteMetadataListingReceiptRead(BaseModel):
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
    provider_client_constructed: bool
    remote_list_performed: bool
    credential_stored: bool
    oauth_authorization_code_stored: bool
    access_token_stored: bool
    refresh_token_stored: bool
    id_token_stored: bool
    client_secret_stored: bool
    private_key_stored: bool
    provider_client_stored: bool
    provider_response_body_stored: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    checkpoint_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
