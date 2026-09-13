from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class PhysicalDisposalExecutionRequest(BaseModel):
    request_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class PhysicalDisposalExecutionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    ao_health_qualification_id: UUID
    binding_hash: str
    file_hash: str
    file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_read_source: str
    target_hash: str
    status: str
    local_existed_before: bool
    local_deleted: bool
    local_absent_after: bool
    recovery_verified_before: bool
    recovery_verified_after: bool
    deleted_at: datetime | None
    verified_at: datetime | None
    outcome_hash: str | None
    s3_delete_performed: bool
    document_row_deleted: bool
    document_storage_key_mutated: bool

    @field_serializer("deleted_at", "verified_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class PhysicalDisposalExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    authorization_id: UUID
    request_id: UUID
    authorization_hash: str
    approval_hash: str
    document_bindings_hash: str
    execution_request_hash: str
    executor_id: UUID
    execution_reason: str
    prepared_at: datetime
    completed_at: datetime | None
    status: str
    document_count: int
    deleted_count: int
    execution_hash: str | None
    destructive_action_performed: bool
    local_delete_performed: bool
    s3_delete_performed: bool
    recovery_bytes_preserved: bool
    document_row_deleted: bool
    document_storage_key_mutated: bool
    items: list[PhysicalDisposalExecutionItemRead] = Field(default_factory=list)

    @field_serializer("prepared_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class PhysicalDisposalExecutionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    execution_request_hash: str
    execution_hash: str | None
    prior_receipt_hash: str | None
    receipt_hash: str
    destructive_action_performed: bool
    local_delete_performed: bool
    s3_delete_performed: bool
    recovery_bytes_preserved: bool
    document_row_deleted: bool
    document_storage_key_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
