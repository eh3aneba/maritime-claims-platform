from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryRoutableDualWriteCanaryHealthRequest(BaseModel):
    canary_lease_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryRoutableDualWriteCanaryHealthReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryRoutableDualWriteCanaryHealthQualificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    canary_lease_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_z_health_qualification_id: UUID
    execution_id: UUID
    phase_x_authorization_id: UUID
    replica_id: UUID
    activation_receipt_id: UUID
    terminal_receipt_id: UUID
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_z_health_qualification_hash: str
    execution_hash: str
    phase_x_authorization_hash: str
    replica_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    verification_hash: str
    lease_snapshot_hash: str
    lease_hash: str
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
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
    health_state: str
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
    qualified_by_id: UUID | None
    qualified_at: datetime | None
    qualification_reason: str | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    local_authoritative: bool
    storage_write_performed: bool
    canary_reactivated: bool
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


class RecoveryRoutableDualWriteCanaryHealthReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    health_qualification_id: UUID
    canary_lease_id: UUID
    phase: str
    health_state: str
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_authoritative: bool
    storage_write_performed: bool
    canary_reactivated: bool
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


class RecoveryRoutableDualWriteCanaryHealthOperationRead(BaseModel):
    qualification: RecoveryRoutableDualWriteCanaryHealthQualificationRead
    receipt: RecoveryRoutableDualWriteCanaryHealthReceiptRead | None
    outcome: str
