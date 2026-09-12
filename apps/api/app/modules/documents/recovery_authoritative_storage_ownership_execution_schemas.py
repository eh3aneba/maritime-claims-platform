from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAuthoritativeStorageOwnershipActivationRequest(BaseModel):
    authorization_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageOwnershipReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageOwnershipLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_ai_health_qualification_id: UUID
    durable_write_ownership_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_ai_health_qualification_hash: str
    durable_write_ownership_lease_hash: str
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
    durable_route_version_at_activation: int
    authority_route_version_before_activation: int
    authority_route_version_after_activation: int
    activation_snapshot_hash: str
    lease_hash: str
    status: str
    ownership_transition_active: bool
    local_authoritative: bool
    recovery_authoritative: bool
    authoritative_storage_changed: bool
    local_evidence_preserved: bool
    activated_by_id: UUID
    activated_at: datetime
    expires_at: datetime
    activation_reason: str
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    storage_write_performed: bool
    read_path_switched: bool
    write_route_mutation_performed: bool
    document_storage_key_mutated: bool
    destructive_action_performed: bool
    physical_disposal_authorized: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryAuthoritativeStorageOwnershipRouteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authority_kind: str
    active_authority_lease_id: UUID | None
    route_version: int
    local_authoritative: bool
    recovery_authoritative: bool
    authoritative_storage_changed: bool
    local_evidence_preserved: bool
    changed_by_id: UUID
    changed_at: datetime
    storage_write_performed: bool
    read_path_switched: bool
    write_route_mutation_performed: bool
    document_storage_key_mutated: bool
    destructive_action_performed: bool
    physical_disposal_authorized: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_overwrite_performed: bool
    local_move_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryAuthoritativeStorageOwnershipReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    lease_id: UUID
    authorization_id: UUID
    phase: str
    from_authority_kind: str
    to_authority_kind: str
    route_version: int
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_ai_health_qualification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    activation_snapshot_hash: str
    lease_hash: str
    receipt_hash: str
    local_authoritative: bool
    recovery_authoritative: bool
    authoritative_storage_changed: bool
    local_evidence_preserved: bool
    storage_write_performed: bool
    read_path_switched: bool
    write_route_mutation_performed: bool
    document_storage_key_mutated: bool
    destructive_action_performed: bool
    physical_disposal_authorized: bool
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


class RecoveryAuthoritativeStorageOwnershipOperationRead(BaseModel):
    lease: RecoveryAuthoritativeStorageOwnershipLeaseRead
    route: RecoveryAuthoritativeStorageOwnershipRouteRead
    receipt: RecoveryAuthoritativeStorageOwnershipReceiptRead | None
    outcome: str
