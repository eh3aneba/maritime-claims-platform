from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDurableReadHealthQualificationRequest(BaseModel):
    durable_lease_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableReadHealthQualificationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableReadHealthQualificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    durable_lease_id: UUID
    activation_receipt_id: UUID
    terminal_receipt_id: UUID
    authorization_id: UUID
    qualification_id: UUID
    replica_id: UUID
    durable_lease_hash: str
    lease_snapshot_hash: str
    activation_receipt_hash: str
    terminal_receipt_hash: str
    authorization_hash: str
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
    terminal_phase: str
    window_started_at: datetime
    window_ended_at: datetime
    verified_durable_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    health_state: str
    operational_evidence_hash: str
    route_version_at_request: int
    request_snapshot_hash: str
    health_qualification_hash: str
    activated_by_id: UUID
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


class RecoveryDurableReadHealthQualificationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    health_qualification_id: UUID
    durable_lease_id: UUID
    phase: str
    health_state: str
    operational_evidence_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
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


class RecoveryDurableReadHealthQualificationOperationRead(BaseModel):
    qualification: RecoveryDurableReadHealthQualificationRead
    receipt: RecoveryDurableReadHealthQualificationReceiptRead | None
    outcome: str
