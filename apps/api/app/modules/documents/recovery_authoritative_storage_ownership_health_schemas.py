from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAuthoritativeStorageOwnershipHealthRequest(BaseModel):
    authoritative_storage_ownership_lease_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageOwnershipHealthReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageOwnershipHealthQualificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authoritative_storage_ownership_lease_id: UUID
    authorization_id: UUID
    activation_receipt_id: UUID
    phase_ai_health_qualification_id: UUID
    durable_write_ownership_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_approval_receipt_hash: str
    activation_receipt_hash: str
    activation_snapshot_hash: str
    lease_hash: str
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
    authority_route_version_at_request: int
    read_route_version_at_request: int
    experimental_write_route_version_at_request: int
    durable_route_version_at_request: int
    observed_authority_kind: str
    observed_ownership_transition_active: bool
    observed_local_authoritative: bool
    observed_recovery_authoritative: bool
    observed_authoritative_storage_changed: bool
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
    health_state: str
    phase_ak_activated_by_id: UUID
    phase_aj_requested_by_id: UUID
    phase_aj_approved_by_id: UUID
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
    qualified_by_id: UUID | None
    qualified_at: datetime | None
    qualification_reason: str | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    local_evidence_preserved: bool
    storage_write_performed: bool
    route_mutation_performed: bool
    ownership_mutation_performed: bool
    read_path_switched: bool
    write_path_switched: bool
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


class RecoveryAuthoritativeStorageOwnershipHealthReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    health_qualification_id: UUID
    authoritative_storage_ownership_lease_id: UUID
    phase: str
    health_state: str
    observed_authority_kind: str
    observed_ownership_transition_active: bool
    observed_local_authoritative: bool
    observed_recovery_authoritative: bool
    observed_authoritative_storage_changed: bool
    authority_route_version: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    local_evidence_preserved: bool
    storage_write_performed: bool
    route_mutation_performed: bool
    ownership_mutation_performed: bool
    read_path_switched: bool
    write_path_switched: bool
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


class RecoveryAuthoritativeStorageOwnershipHealthOperationRead(BaseModel):
    qualification: RecoveryAuthoritativeStorageOwnershipHealthQualificationRead
    receipt: RecoveryAuthoritativeStorageOwnershipHealthReceiptRead | None
    outcome: str
