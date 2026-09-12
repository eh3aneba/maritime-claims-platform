from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAuthoritativeStorageOwnershipAuthorizationRequest(BaseModel):
    health_qualification_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageOwnershipAuthorizationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageOwnershipAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    phase_ai_health_qualification_id: UUID
    phase_ai_health_receipt_id: UUID
    durable_write_ownership_lease_id: UUID
    phase_ag_authorization_id: UUID
    replica_id: UUID
    phase_ai_health_qualification_hash: str
    phase_ai_health_receipt_hash: str
    phase_ai_request_snapshot_hash: str
    phase_ai_integrity_proof_hash: str
    durable_write_ownership_lease_hash: str
    phase_ag_authorization_hash: str
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
    experimental_write_route_version_at_request: int
    durable_route_version_at_request: int
    current_authority_kind: str
    target_authority_kind: str
    request_snapshot_hash: str
    authorization_hash: str
    health_state: str
    max_execution_windows: int
    phase_ai_requested_by_id: UUID
    phase_ai_qualified_by_id: UUID
    phase_ah_activated_by_id: UUID
    phase_ag_requested_by_id: UUID
    phase_ag_approved_by_id: UUID
    phase_af_requested_by_id: UUID
    phase_af_qualified_by_id: UUID
    phase_ae_activated_by_id: UUID
    phase_ad_requested_by_id: UUID
    phase_ad_approved_by_id: UUID
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
    route_mutation_performed: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
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


class RecoveryAuthoritativeStorageOwnershipAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    phase_ai_health_qualification_id: UUID
    phase: str
    health_state: str
    current_authority_kind: str
    target_authority_kind: str
    phase_ai_health_qualification_hash: str
    phase_ai_health_receipt_hash: str
    request_snapshot_hash: str
    authorization_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_authoritative: bool
    storage_write_performed: bool
    route_mutation_performed: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
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


class RecoveryAuthoritativeStorageOwnershipAuthorizationOperationRead(BaseModel):
    authorization: RecoveryAuthoritativeStorageOwnershipAuthorizationRead
    receipt: RecoveryAuthoritativeStorageOwnershipAuthorizationReceiptRead | None
    outcome: str
