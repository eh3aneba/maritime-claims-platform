from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryRoutableDualWriteCanaryExecutionReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryRoutableDualWriteCanaryLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_z_health_qualification_id: UUID
    execution_id: UUID
    phase_x_authorization_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_approval_receipt_hash: str
    phase_z_health_qualification_hash: str
    execution_hash: str
    phase_x_authorization_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    read_route_version_at_activation: int
    write_route_version_at_activation: int
    canary_object_key_fingerprint: str
    observed_file_hash: str
    observed_file_size_bytes: int
    remote_etag: str | None
    verification_hash: str
    lease_snapshot_hash: str
    lease_hash: str
    status: str
    max_canary_writes: int
    storage_write_performed: bool
    canary_executed: bool
    canary_write_verified: bool
    routable_dual_write_active: bool
    activated_by_id: UUID
    activated_at: datetime
    lease_expires_at: datetime
    activation_reason: str
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    local_authoritative: bool
    durable_write_authority_created: bool
    rehearsal_object_routable: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryRoutableDualWriteCanaryReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    canary_lease_id: UUID
    authorization_id: UUID
    phase: str
    from_write_mode: str
    to_write_mode: str
    authorization_hash: str
    authorization_approval_receipt_hash: str
    canary_object_key_fingerprint: str
    source_file_hash: str
    source_file_size_bytes: int
    verification_hash: str
    lease_hash: str
    receipt_hash: str
    storage_write_performed: bool
    canary_executed: bool
    canary_write_verified: bool
    routable_dual_write_active: bool
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_authoritative: bool
    durable_write_authority_created: bool
    rehearsal_object_routable: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryRoutableDualWriteCanaryOperationRead(BaseModel):
    lease: RecoveryRoutableDualWriteCanaryLeaseRead
    receipt: RecoveryRoutableDualWriteCanaryReceiptRead | None
    outcome: str
