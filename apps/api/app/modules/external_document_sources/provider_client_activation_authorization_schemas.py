from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceProviderClientActivationAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceProviderClientActivationAuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceProviderClientActivationAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    health_qualification_id: UUID
    credential_reference_binding_id: UUID
    provider_kind: str
    profile_hash: str
    binding_scope_hash: str
    binding_request_hash: str
    binding_approval_hash: str
    locator_hash: str
    reference_backend: str
    resolver_kind: str
    health_scope_hash: str
    health_request_hash: str
    health_result_hash: str
    health_result_status: str
    request_key: str
    scope_hash: str
    request_hash: str
    execution_limit: int
    status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    review_expires_at: datetime
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    authorization_hash: str | None
    authorization_expires_at: datetime | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    terminal_hash: str | None
    credential_reference_stored: bool
    credential_reference_resolution_performed: bool
    credential_stored: bool
    oauth_authorization_code_stored: bool
    oauth_token_exchanged: bool
    access_token_stored: bool
    refresh_token_stored: bool
    client_secret_stored: bool
    private_key_stored: bool
    provider_network_performed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    checkpoint_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    provider_client_activation_authorized: bool

    @field_serializer(
        "requested_at",
        "review_expires_at",
        "approved_at",
        "authorization_expires_at",
        "terminal_at",
    )
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceProviderClientActivationAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    authorization_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID | None
    occurred_at: datetime
    reason: str
    scope_hash: str
    decision_hash: str
    prior_receipt_hash: str | None
    receipt_hash: str
    credential_reference_stored: bool
    credential_reference_resolution_performed: bool
    credential_stored: bool
    oauth_authorization_code_stored: bool
    oauth_token_exchanged: bool
    access_token_stored: bool
    refresh_token_stored: bool
    client_secret_stored: bool
    private_key_stored: bool
    provider_network_performed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    checkpoint_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    provider_client_activation_authorized: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
