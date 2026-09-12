from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDurableWriteOwnershipActivationRequest(BaseModel):
    authorization_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableWriteOwnershipReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableWriteOwnershipLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_af_health_qualification_id: UUID
    transition_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_approval_receipt_hash: str
    phase_af_health_qualification_hash: str
    phase_af_health_receipt_hash: str
    transition_lease_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    observed_local_hash: str
    observed_local_size_bytes: int
    observed_recovery_hash: str
    observed_recovery_size_bytes: int
    observed_recovery_etag: str | None
    read_route_version_at_activation: int
    experimental_write_route_version_at_activation: int
    durable_route_version_before_activation: int
    durable_route_version_after_activation: int
    activation_snapshot_hash: str
    lease_hash: str
    status: str
    durable_write_ownership_active: bool
    durable_write_authority_created: bool
    write_path_switched: bool
    activated_by_id: UUID
    activated_at: datetime
    activation_reason: str
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    local_authoritative: bool
    storage_write_performed: bool
    read_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDurableWriteOwnershipRouteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    write_mode: str
    active_durable_write_ownership_lease_id: UUID | None
    route_version: int
    durable_write_authority_created: bool
    write_path_switched: bool
    changed_by_id: UUID
    changed_at: datetime
    local_authoritative: bool
    storage_write_performed: bool
    read_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDurableWriteOwnershipReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    lease_id: UUID
    authorization_id: UUID
    phase: str
    from_write_mode: str
    to_write_mode: str
    route_version: int
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_af_health_qualification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    activation_snapshot_hash: str
    lease_hash: str
    receipt_hash: str
    durable_write_ownership_active: bool
    durable_write_authority_created: bool
    write_path_switched: bool
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_authoritative: bool
    storage_write_performed: bool
    read_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDurableWriteOwnershipOperationRead(BaseModel):
    lease: RecoveryDurableWriteOwnershipLeaseRead
    route: RecoveryDurableWriteOwnershipRouteRead
    receipt: RecoveryDurableWriteOwnershipReceiptRead | None
    outcome: str
