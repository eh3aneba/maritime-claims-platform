from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDurableReadPromotionAuthorizationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDurableReadPromotionAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    qualification_id: UUID
    qualification_receipt_id: UUID
    replica_id: UUID
    qualification_hash: str
    qualification_bundle_hash: str
    qualification_request_snapshot_hash: str
    qualification_receipt_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    route_version_at_request: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    authorization_hash: str
    phase_k_qualified_by_id: UUID
    first_activated_by_id: UUID
    second_activated_by_id: UUID
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


class RecoveryDurableReadPromotionAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authorization_id: UUID
    qualification_id: UUID
    phase: str
    qualification_hash: str
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


class RecoveryDurableReadPromotionAuthorizationOperationRead(BaseModel):
    authorization: RecoveryDurableReadPromotionAuthorizationRead
    receipt: RecoveryDurableReadPromotionAuthorizationReceiptRead | None
    outcome: str
