from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecoveryRoutableReadQualificationRequest(BaseModel):
    cutover_lease_ids: list[UUID] = Field(min_length=2, max_length=2)
    reason: str = Field(min_length=8, max_length=2000)

    @field_validator("cutover_lease_ids")
    @classmethod
    def require_distinct_leases(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != 2:
            raise ValueError("Two distinct routable read cutover leases are required")
        return value


class RecoveryRoutableReadQualificationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryRoutableReadQualificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    replica_id: UUID
    first_cutover_lease_id: UUID
    second_cutover_lease_id: UUID
    first_authorization_id: UUID
    second_authorization_id: UUID
    first_activation_receipt_id: UUID
    first_rollback_receipt_id: UUID
    second_activation_receipt_id: UUID
    second_rollback_receipt_id: UUID
    first_lease_hash: str
    second_lease_hash: str
    first_activation_receipt_hash: str
    first_rollback_receipt_hash: str
    second_activation_receipt_hash: str
    second_rollback_receipt_hash: str
    first_cycle_proof_hash: str
    second_cycle_proof_hash: str
    qualification_bundle_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    route_version_at_request: int
    request_snapshot_hash: str
    qualification_hash: str
    successful_cycle_count: int
    first_activated_by_id: UUID
    second_activated_by_id: UUID
    requested_by_id: UUID
    requested_at: datetime
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
    routable_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryRoutableReadQualificationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    qualification_id: UUID
    phase: str
    qualification_bundle_hash: str
    request_snapshot_hash: str
    qualification_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    routable_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryRoutableReadQualificationOperationRead(BaseModel):
    qualification: RecoveryRoutableReadQualificationRead
    receipt: RecoveryRoutableReadQualificationReceiptRead | None
    outcome: str
