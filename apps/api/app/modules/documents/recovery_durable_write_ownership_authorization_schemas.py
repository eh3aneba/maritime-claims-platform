from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDurableWriteOwnershipAuthorizationRequest(BaseModel):
    health_qualification_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableWriteOwnershipAuthorizationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableWriteOwnershipAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    phase_af_health_qualification_id: UUID
    phase_af_health_receipt_id: UUID
    transition_lease_id: UUID
    phase_ad_authorization_id: UUID
    replica_id: UUID
    phase_af_health_qualification_hash: str
    phase_af_health_receipt_hash: str
    phase_af_request_snapshot_hash: str
    phase_af_integrity_proof_hash: str
    transition_lease_hash: str
    phase_ad_authorization_hash: str
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
    read_route_version_at_request: int
    write_route_version_at_request: int
    request_snapshot_hash: str
    authorization_hash: str
    health_state: str
    max_execution_windows: int
    phase_af_requested_by_id: UUID
    phase_af_qualified_by_id: UUID
    phase_ae_activated_by_id: UUID
    phase_ad_requested_by_id: UUID
    phase_ad_approved_by_id: UUID
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
    write_route_reactivated: bool
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
    created_at: datetime
    updated_at: datetime


class RecoveryDurableWriteOwnershipAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    phase_af_health_qualification_id: UUID
    phase: str
    health_state: str
    phase_af_health_qualification_hash: str
    phase_af_health_receipt_hash: str
    request_snapshot_hash: str
    authorization_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_authoritative: bool
    storage_write_performed: bool
    write_route_lease_created: bool
    write_route_reactivated: bool
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
    created_at: datetime
    updated_at: datetime


class RecoveryDurableWriteOwnershipAuthorizationOperationRead(BaseModel):
    authorization: RecoveryDurableWriteOwnershipAuthorizationRead
    receipt: RecoveryDurableWriteOwnershipAuthorizationReceiptRead | None
    outcome: str
