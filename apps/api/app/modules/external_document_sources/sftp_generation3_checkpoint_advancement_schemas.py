from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpGeneration3CheckpointAdvancementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    generation3_restaging_id: UUID
    predecessor_checkpoint_advancement_id: UUID
    successor_change_detection_id: UUID
    predecessor_successor_restaging_id: UUID
    provider_kind: str
    profile_hash: str
    predecessor_checkpoint_generation: int
    predecessor_checkpoint_state_hash: str
    predecessor_checkpoint_completion_hash: str
    candidate_scope_hash: str
    candidate_request_hash: str
    candidate_content_proof_hash: str
    candidate_completion_hash: str
    candidate_generation: int
    observation_scope_hash: str
    observation_completion_hash: str
    content_sha256: str
    content_byte_count: int
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
    successor_checkpoint_kind: str
    successor_checkpoint_generation: int
    successor_checkpoint_state_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    result_status: str | None
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    completed_at: datetime | None
    completion_hash: str | None

    credential_reference_stored: bool
    upstream_checkpoint_completed: bool
    upstream_successor_change_detection_completed: bool
    upstream_generation3_restaging_completed: bool
    secret_resolution_performed: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    host_key_verification_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_stat_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_rename_performed: bool
    remote_delete_performed: bool
    remote_mkdir_performed: bool
    remote_chmod_performed: bool
    remote_chown_performed: bool
    remote_touch_performed: bool
    command_executed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_reconciliation_performed: bool
    storage_delete_performed: bool
    storage_copy_performed: bool
    durable_content_staged: bool
    checkpoint_created: bool
    checkpoint_advanced: bool
    credential_stored: bool
    session_stored: bool
    raw_response_stored: bool
    remote_content_stored: bool
    remote_content_returned: bool
    remote_content_logged: bool
    content_parsed: bool
    content_extracted: bool
    evidence_admitted: bool
    document_created: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool

    @field_serializer("requested_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    advancement_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    scope_hash: str
    decision_hash: str
    prior_receipt_hash: str | None
    receipt_hash: str

    credential_reference_stored: bool
    upstream_checkpoint_completed: bool
    upstream_successor_change_detection_completed: bool
    upstream_generation3_restaging_completed: bool
    secret_resolution_performed: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    host_key_verification_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_stat_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_rename_performed: bool
    remote_delete_performed: bool
    remote_mkdir_performed: bool
    remote_chmod_performed: bool
    remote_chown_performed: bool
    remote_touch_performed: bool
    command_executed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_reconciliation_performed: bool
    storage_delete_performed: bool
    storage_copy_performed: bool
    durable_content_staged: bool
    checkpoint_created: bool
    checkpoint_advanced: bool
    credential_stored: bool
    session_stored: bool
    raw_response_stored: bool
    remote_content_stored: bool
    remote_content_returned: bool
    remote_content_logged: bool
    content_parsed: bool
    content_extracted: bool
    evidence_admitted: bool
    document_created: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
