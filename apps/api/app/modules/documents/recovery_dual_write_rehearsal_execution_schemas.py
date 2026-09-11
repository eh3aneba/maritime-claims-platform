from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryDualWriteRehearsalExecutionReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryDualWriteRehearsalExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    phase_x_authorization_id: UUID
    phase_x_approval_receipt_id: UUID
    phase_w_health_qualification_id: UUID
    phase_v_transition_lease_id: UUID
    phase_u_authorization_id: UUID
    phase_t_health_qualification_id: UUID
    replica_id: UUID
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
    route_version_at_execution: int
    rehearsal_object_key_fingerprint: str
    observed_file_hash: str
    observed_file_size_bytes: int
    remote_etag: str | None
    verification_hash: str
    execution_hash: str
    max_rehearsal_writes: int
    conditional_write_performed: bool
    status: str
    executed_by_id: UUID
    executed_at: datetime
    execution_reason: str
    rehearsal_executed: bool
    rehearsal_write_verified: bool
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


class RecoveryDualWriteRehearsalExecutionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    execution_id: UUID
    phase_x_authorization_id: UUID
    phase: str
    phase_x_authorization_hash: str
    phase_x_approval_receipt_hash: str
    rehearsal_object_key_fingerprint: str
    source_file_hash: str
    source_file_size_bytes: int
    verification_hash: str
    execution_hash: str
    receipt_hash: str
    conditional_write_performed: bool
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    rehearsal_executed: bool
    rehearsal_write_verified: bool
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


class RecoveryDualWriteRehearsalExecutionOperationRead(BaseModel):
    execution: RecoveryDualWriteRehearsalExecutionRead
    receipt: RecoveryDualWriteRehearsalExecutionReceiptRead | None
    outcome: str
