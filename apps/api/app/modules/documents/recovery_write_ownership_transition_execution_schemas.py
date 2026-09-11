from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryWriteOwnershipTransitionExecutionReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryWriteOwnershipTransitionLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_ac_health_qualification_id: UUID
    canary_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_approval_receipt_hash: str
    phase_ac_health_qualification_hash: str
    phase_ac_health_receipt_hash: str
    canary_lease_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    observed_replica_hash: str
    observed_replica_size_bytes: int
    observed_replica_etag: str | None
    read_route_version_at_activation: int
    write_route_version_before_activation: int
    write_route_version_after_activation: int
    activation_snapshot_hash: str
    lease_hash: str
    status: str
    bounded_write_ownership_transition_active: bool
    local_authoritative: bool
    storage_write_performed: bool
    durable_write_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    activated_by_id: UUID
    activated_at: datetime
    route_expires_at: datetime
    activation_reason: str
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    created_at: datetime
    updated_at: datetime


class RecoveryWriteOwnershipTransitionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    transition_lease_id: UUID
    authorization_id: UUID
    phase: str
    from_write_mode: str
    to_write_mode: str
    route_version: int
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_ac_health_qualification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    observed_replica_hash: str
    observed_replica_size_bytes: int
    activation_snapshot_hash: str
    lease_hash: str
    receipt_hash: str
    bounded_write_ownership_transition_active: bool
    local_authoritative: bool
    storage_write_performed: bool
    durable_write_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryWriteOwnershipTransitionOperationRead(BaseModel):
    lease: RecoveryWriteOwnershipTransitionLeaseRead
    receipt: RecoveryWriteOwnershipTransitionReceiptRead | None
    outcome: str
