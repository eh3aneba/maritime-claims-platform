from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDurableReadRenewalLeaseReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableReadRenewalLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    health_qualification_id: UUID
    prior_durable_lease_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_integrity_proof_hash: str
    authorization_approval_receipt_hash: str
    health_qualification_hash: str
    operational_evidence_hash: str
    prior_durable_lease_hash: str
    prior_lease_snapshot_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    verified_durable_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_version_at_prepare: int
    integrity_proof_hash: str
    lease_snapshot_hash: str
    lease_hash: str
    status: str
    activation_expires_at: datetime
    route_expires_at: datetime | None
    authorization_approved_by_id: UUID
    prior_durable_activated_by_id: UUID
    prepared_by_id: UUID
    prepared_at: datetime
    preparation_reason: str
    activated_by_id: UUID | None
    activated_at: datetime | None
    activation_reason: str | None
    rolled_back_by_id: UUID | None
    rolled_back_at: datetime | None
    rollback_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    routable_authority_created: bool
    durable_read_route_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDurableReadRenewalReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    renewal_lease_id: UUID
    authorization_id: UUID
    phase: str
    from_route_class: str
    to_route_class: str
    route_authority_kind: str
    route_version: int
    lease_snapshot_hash: str
    lease_hash: str
    authorization_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    routable_authority_created: bool
    durable_read_route_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDurableReadRenewalRouteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    route_class: str
    route_authority_kind: str
    durable_authority_active: bool
    active_lease_id: UUID | None
    active_durable_lease_id: UUID | None
    active_durable_renewal_lease_id: UUID | None
    active_replica_id: UUID | None
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    route_version: int
    changed_by_id: UUID
    changed_at: datetime
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool


class RecoveryDurableReadRenewalOperationRead(BaseModel):
    lease: RecoveryDurableReadRenewalLeaseRead
    route: RecoveryDurableReadRenewalRouteRead
    receipt: RecoveryDurableReadRenewalReceiptRead | None
    outcome: str
