from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


ProviderKind = Literal["sharepoint", "google_drive"]


class ExternalDocumentSourceProfileRequest(BaseModel):
    provider_kind: ProviderKind
    display_name: str = Field(min_length=3, max_length=200)
    config: dict[str, Any]
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceProfileDecision(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_kind: str
    display_name: str
    normalized_config: dict[str, Any]
    config_hash: str
    profile_hash: str
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
    credential_stored: bool
    oauth_token_exchanged: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    live_connection_authorized: bool

    @field_serializer("requested_at", "approved_at", "terminal_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceProfileReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    profile_hash: str
    decision_hash: str | None
    prior_receipt_hash: str | None
    receipt_hash: str
    credential_stored: bool
    oauth_token_exchanged: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    subscription_created: bool
    sync_executed: bool
    evidence_admitted: bool
    document_created: bool
    claim_mutated: bool
    live_connection_authorized: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
