from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAuthoritativeStorageRatificationExecutionRequest(BaseModel):
    authorization_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritativeStorageRatificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    phase_al_health_qualification_id: UUID
    authoritative_storage_ownership_lease_id: UUID
    phase_aj_authorization_id: UUID
    phase_ai_health_qualification_id: UUID
    durable_write_ownership_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_al_health_qualification_hash: str
    phase_al_health_receipt_hash: str
    phase_al_integrity_proof_hash: str
    authoritative_storage_ownership_lease_hash: str
    phase_aj_authorization_hash: str
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
    authority_route_version_before_ratification: int
    authority_route_version_after_ratification: int
    read_route_version_at_ratification: int
    experimental_write_route_version_at_ratification: int
    durable_route_version_at_ratification: int
    execution_snapshot_hash: str
    ratification_hash: str
    status: str
    authority_kind: str
    authority_tenure: str
    ratification_active: bool
    durable_authority_created: bool
    local_authoritative: bool
    recovery_authoritative: bool
    authoritative_storage_changed: bool
    executed_by_id: UUID
    executed_at: datetime
    execution_reason: str
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


class RecoveryAuthoritativeStorageRatificationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    ratification_id: UUID
    authorization_id: UUID
    phase: str
    from_authority_kind: str
    to_authority_kind: str
    from_authority_tenure: str
    to_authority_tenure: str
    route_version: int
    authorization_hash: str
    authorization_approval_receipt_hash: str
    phase_al_health_qualification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    execution_snapshot_hash: str
    ratification_hash: str
    receipt_hash: str
    ratification_active: bool
    durable_authority_created: bool
    local_authoritative: bool
    recovery_authoritative: bool
    authoritative_storage_changed: bool
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


class RecoveryAuthoritativeStorageRatificationRouteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authority_kind: str
    authority_tenure: str
    active_authority_lease_id: UUID | None
    durable_ratification_id: UUID | None
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


class RecoveryAuthoritativeStorageRatificationOperationRead(BaseModel):
    ratification: RecoveryAuthoritativeStorageRatificationRead
    route: RecoveryAuthoritativeStorageRatificationRouteRead
    receipt: RecoveryAuthoritativeStorageRatificationReceiptRead | None
    outcome: str