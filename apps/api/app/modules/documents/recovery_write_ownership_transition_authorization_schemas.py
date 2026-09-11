from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryWriteOwnershipTransitionAuthorizationRequest(BaseModel):
    health_qualification_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryWriteOwnershipTransitionAuthorizationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryWriteOwnershipTransitionAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    phase_ac_health_qualification_id: UUID
    phase_ac_health_receipt_id: UUID
    canary_lease_id: UUID
    phase_aa_authorization_id: UUID
    phase_aa_approval_receipt_id: UUID
    phase_z_health_qualification_id: UUID
    execution_id: UUID
    phase_x_authorization_id: UUID
    replica_id: UUID
    phase_ac_health_qualification_hash: str
    phase_ac_health_receipt_hash: str
    phase_ac_request_snapshot_hash: str
    phase_ac_integrity_proof_hash: str
    lease_hash: str
    lease_snapshot_hash: str
    verification_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    phase_aa_authorization_hash: str
    phase_aa_approval_receipt_hash: str
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
    canary_object_key_fingerprint: str
    observed_file_hash: str
    observed_file_size_bytes: int
    remote_etag: str | None
    read_route_version_at_request: int
    write_route_version_at_request: int
    request_snapshot_hash: str
    authorization_hash: str
    health_state: str
    max_transition_windows: int
    phase_ac_qualified_by_id: UUID
    phase_ab_activated_by_id: UUID
    phase_aa_requested_by_id: UUID
    phase_aa_approved_by_id: UUID
    phase_z_qualified_by_id: UUID
    phase_y_executed_by_id: UUID
    phase_x_approved_by_id: UUID
    requested_by_id: UUID
    requested_at: datetime
    review_expires_at: datetime
    request_reason: str
    status: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    authorization_expires_at: datetime | None
    approval_reason: str | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    local_authoritative: bool
    storage_write_performed: bool
    write_route_lease_created: bool
    routable_dual_write_active: bool
    durable_write_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryWriteOwnershipTransitionAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    phase_ac_health_qualification_id: UUID
    phase: str
    health_state: str
    phase_ac_health_qualification_hash: str
    phase_ac_health_receipt_hash: str
    request_snapshot_hash: str
    authorization_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_authoritative: bool
    storage_write_performed: bool
    write_route_lease_created: bool
    routable_dual_write_active: bool
    durable_write_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_put_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryWriteOwnershipTransitionAuthorizationOperationRead(BaseModel):
    authorization: RecoveryWriteOwnershipTransitionAuthorizationRead
    receipt: RecoveryWriteOwnershipTransitionAuthorizationReceiptRead | None
    outcome: str
