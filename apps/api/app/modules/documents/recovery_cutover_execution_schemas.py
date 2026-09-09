from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryCutoverExecutionReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryCutoverExecutionLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    cutover_admission_id: UUID
    admission_approval_receipt_id: UUID
    authority_switch_rehearsal_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    admission_hash: str
    admission_request_snapshot_hash: str
    admission_approval_receipt_hash: str
    transition_proof_hash: str
    rehearsal_contract_hash: str
    rehearsal_lineage_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    execution_snapshot_hash: str
    lease_hash: str
    status: str
    lease_expires_at: datetime
    admission_approved_by_id: UUID
    prepared_by_id: UUID
    prepared_at: datetime
    preparation_reason: str
    activated_by_id: UUID | None
    activated_at: datetime | None
    activation_reason: str | None
    rolled_back_by_id: UUID | None
    rolled_back_at: datetime | None
    rollback_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    read_path_switched: bool
    document_storage_key_mutated: bool
    active_backend_changed: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryCutoverExecutionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    execution_lease_id: UUID
    cutover_admission_id: UUID
    phase: str
    from_state: str
    to_state: str
    admission_hash: str
    admission_approval_receipt_hash: str
    execution_snapshot_hash: str
    lease_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    read_path_switched: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryCutoverExecutionOperationRead(BaseModel):
    lease: RecoveryCutoverExecutionLeaseRead
    receipt: RecoveryCutoverExecutionReceiptRead | None
    outcome: str
