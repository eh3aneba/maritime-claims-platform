from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PhysicalDisposalAdmissionRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class PhysicalDisposalAdmissionDecision(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class PhysicalDisposalAdmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    disposal_release_review_id: UUID
    disposal_quarantine_stage_id: UUID
    disposal_execution_manifest_id: UUID
    release_review_hash: str
    release_approval_hash: str
    manifest_hash: str
    inventory_hash: str
    document_bindings: list[dict[str, Any]]
    document_bindings_hash: str
    separation_actor_set_hash: str
    document_count: int
    total_file_size_bytes: int
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    authorization_expires_at: datetime
    status: str
    physical_disposal_authorized: bool
    max_execution_count: int
    execution_count: int
    authorization_hash: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    approval_hash: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    destructive_action_performed: bool
    storage_write_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class PhysicalDisposalAdmissionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    authorization_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    authorization_hash: str
    document_bindings_hash: str
    separation_actor_set_hash: str
    approval_hash: str | None
    prior_receipt_hash: str | None
    receipt_hash: str
    destructive_action_performed: bool
    storage_write_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime