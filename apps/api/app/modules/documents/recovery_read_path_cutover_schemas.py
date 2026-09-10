from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryReadPathCutoverAuthorizationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryReadPathCutoverAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    execution_lease_id: UUID
    execution_activation_receipt_id: UUID
    execution_rollback_receipt_id: UUID
    cutover_admission_id: UUID
    admission_approval_receipt_id: UUID
    authority_switch_rehearsal_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    lease_hash: str
    execution_snapshot_hash: str
    execution_activation_receipt_hash: str
    execution_rollback_receipt_hash: str
    execution_transition_proof_hash: str
    admission_hash: str
    admission_approval_receipt_hash: str
    rehearsal_contract_hash: str
    rehearsal_lineage_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    request_snapshot_hash: str
    authorization_hash: str
    status: str
    authorization_expires_at: datetime
    execution_activated_by_id: UUID
    requested_by_id: UUID
    requested_at: datetime
    request_reason: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    routable_authority_created: bool
    read_path_switched: bool
    document_storage_key_mutated: bool
    active_backend_changed: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryReadPathCutoverAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    execution_lease_id: UUID
    phase: str
    request_snapshot_hash: str
    authorization_hash: str
    execution_transition_proof_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    routable_authority_created: bool
    read_path_switched: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryReadPathCutoverAuthorizationOperationRead(BaseModel):
    authorization: RecoveryReadPathCutoverAuthorizationRead
    receipt: RecoveryReadPathCutoverAuthorizationReceiptRead | None
    outcome: str
