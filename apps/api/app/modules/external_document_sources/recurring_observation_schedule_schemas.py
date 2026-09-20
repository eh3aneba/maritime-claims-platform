from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


CadenceClass = Literal["hourly", "every_6_hours", "every_12_hours", "daily"]


class ExternalDocumentSourceRecurringObservationScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)
    cadence_class: CadenceClass
    effective_at: datetime | None = None


class ExternalDocumentSourceRecurringObservationScheduleDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceRecurringObservationScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    document_family_id: UUID
    prior_schedule_id: UUID | None
    revision_number: int
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    binding_completion_hash: str
    cadence_class: str
    cadence_minutes: int
    effective_at: datetime
    next_due_at: datetime
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    active_binding_guard: UUID | None
    authorized_by_id: UUID
    authorization_reason: str
    authorized_at: datetime
    authorization_hash: str
    disable_request_key: str | None
    disabled_by_id: UUID | None
    disable_reason: str | None
    disabled_at: datetime | None
    terminal_hash: str | None

    family_binding_verified: bool
    stable_source_identity_verified: bool
    human_authorization_recorded: bool
    bounded_cadence_verified: bool
    provider_client_constructed: bool
    token_acquired: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_mutated: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_worker_started: bool

    @field_serializer("effective_at", "next_due_at", "authorized_at", "disabled_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceRecurringObservationScheduleReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    schedule_id: UUID
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
    stable_source_identity_verified: bool
    human_authorization_recorded: bool
    bounded_cadence_verified: bool
    provider_client_constructed: bool
    token_acquired: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_mutated: bool
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
