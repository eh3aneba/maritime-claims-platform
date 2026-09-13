from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class PhysicalDisposalClosureRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class PhysicalDisposalClosureDecision(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class PhysicalDisposalClosureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    execution_id: UUID
    authorization_id: UUID
    execution_request_hash: str
    execution_hash: str
    document_bindings_hash: str
    execution_receipt_chain_hash: str
    item_outcomes_hash: str
    verification_snapshot: list[dict[str, Any]]
    verification_snapshot_hash: str
    separation_actor_set_hash: str
    document_count: int
    total_file_size_bytes: int
    observed_local_targets_absent: bool
    observed_recovery_bytes_healthy: bool
    observed_document_rows_preserved: bool
    observed_storage_keys_preserved: bool
    observed_authority_kind: str
    observed_authority_tenure: str
    health_state: str
    phase_17_4_b_executor_id: UUID
    phase_17_4_a_requested_by_id: UUID
    phase_17_4_a_approved_by_id: UUID
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    review_expires_at: datetime
    closure_qualification_hash: str
    status: str
    qualified_by_id: UUID | None
    qualified_at: datetime | None
    qualification_reason: str | None
    decision_hash: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    storage_write_performed: bool
    route_mutation_performed: bool
    ownership_mutation_performed: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    destructive_action_performed: bool
    physical_disposal_authorized: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool

    @field_serializer("requested_at", "review_expires_at", "qualified_at", "terminal_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class PhysicalDisposalClosureReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    qualification_id: UUID
    execution_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    execution_hash: str
    verification_snapshot_hash: str
    closure_qualification_hash: str
    decision_hash: str | None
    prior_receipt_hash: str | None
    receipt_hash: str
    storage_write_performed: bool
    route_mutation_performed: bool
    ownership_mutation_performed: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    destructive_action_performed: bool
    physical_disposal_authorized: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
