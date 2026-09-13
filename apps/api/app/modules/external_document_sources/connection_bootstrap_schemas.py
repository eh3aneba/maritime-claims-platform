from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceConnectionBootstrapExecutionRequest(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceConnectionBootstrapExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    discovery_run_id: UUID
    authorization_id: UUID
    provider_kind: str
    profile_hash: str
    discovery_scope_hash: str
    discovery_manifest_hash: str
    discovery_run_hash: str
    authorization_scope_hash: str
    authorization_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    authorization_terminal_hash: str | None
    completed_at: datetime | None
    completion_hash: str | None
    credential_stored: bool
    credential_reference_stored: bool
    oauth_token_exchanged: bool
    provider_network_performed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    authorization_consumed: bool

    @field_serializer("requested_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceConnectionBootstrapExecutionReceiptRead(BaseModel):
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
    credential_stored: bool
    credential_reference_stored: bool
    oauth_token_exchanged: bool
    provider_network_performed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    authorization_consumed: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
