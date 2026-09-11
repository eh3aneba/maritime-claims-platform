from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDualWriteRehearsalHealthQualificationRequest(BaseModel):
    execution_id: UUID
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDualWriteRehearsalHealthQualificationReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDualWriteRehearsalHealthQualificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    execution_id: UUID
    execution_receipt_id: UUID
    phase_x_authorization_id: UUID
    phase_x_approval_receipt_id: UUID
    phase_w_health_qualification_id: UUID
    phase_v_transition_lease_id: UUID
    phase_u_authorization_id: UUID
    phase_t_health_qualification_id: UUID
    replica_id: UUID
    execution_hash: str
    verification_hash: str
    execution_receipt_hash: str
    phase_x_authorization_hash: str
    phase_x_approval_receipt_hash: str
    phase_w_health_qualification_hash: str
    phase_v_transition_lease_hash: str
    phase_u_authorization_hash: str
    phase_t_health_qualification_hash: str
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
    rehearsal_object_key_fingerprint: str
    observed_file_hash: str
    observed_file_size_bytes: int
    remote_etag: str | None
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
    health_state: str
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
    storage_write_performed: bool
    routable_dual_write_authority_created: bool
    rehearsal_object_routable: bool
    dual_write_active: bool
    durable_write_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDualWriteRehearsalHealthReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    health_qualification_id: UUID
    execution_id: UUID
    phase: str
    health_state: str
    integrity_proof_hash: str
    request_snapshot_hash: str
    health_qualification_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    storage_write_performed: bool
    routable_dual_write_authority_created: bool
    rehearsal_object_routable: bool
    dual_write_active: bool
    durable_write_authority_created: bool
    read_path_switched: bool
    write_path_switched: bool
    document_storage_key_mutated: bool
    authoritative_storage_changed: bool
    destructive_action_performed: bool
    s3_copy_performed: bool
    s3_delete_performed: bool
    local_delete_performed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryDualWriteRehearsalHealthOperationRead(BaseModel):
    qualification: RecoveryDualWriteRehearsalHealthQualificationRead
    receipt: RecoveryDualWriteRehearsalHealthReceiptRead | None
    outcome: str
