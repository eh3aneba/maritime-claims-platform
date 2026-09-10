from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDurableReadRenewalAuthorizationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableReadRenewalAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    health_qualification_id: UUID
    health_qualification_receipt_id: UUID
    durable_lease_id: UUID
    activation_receipt_id: UUID
    terminal_receipt_id: UUID
    prior_authorization_id: UUID
    phase_k_qualification_id: UUID
    replica_id: UUID
    health_qualification_hash: str
    health_request_snapshot_hash: str
    health_qualification_receipt_hash: str
    operational_evidence_hash: str
    health_state: str
    durable_lease_hash: str
    lease_snapshot_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    prior_authorization_hash: str
    phase_k_qualification_hash: str
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
    route_version_at_request: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    authorization_hash: str
    health_qualified_by_id: UUID
    durable_activated_by_id: UUID
    status: str
    authorization_expires_at: datetime
    requested_by_id: UUID
    requested_at: datetime
    request_reason: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
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


class RecoveryDurableReadRenewalAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    health_qualification_id: UUID
    durable_lease_id: UUID
    phase: str
    health_qualification_hash: str
    operational_evidence_hash: str
    integrity_proof_hash: str
    request_snapshot_hash: str
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


class RecoveryDurableReadRenewalAuthorizationOperationRead(BaseModel):
    authorization: RecoveryDurableReadRenewalAuthorizationRead
    receipt: RecoveryDurableReadRenewalAuthorizationReceiptRead | None
    outcome: str
