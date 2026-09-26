from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpCheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpCheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    quarantine_staging_id: UUID
    file_content_proof_id: UUID
    directory_listing_id: UUID
    listing_entry_id: UUID
    provider_kind: str
    profile_hash: str
    listing_entry_hash: str
    file_content_proof_result_hash: str
    staging_scope_hash: str
    staging_request_hash: str
    staging_completion_hash: str
    content_sha256: str
    content_byte_count: int
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
    checkpoint_kind: str
    checkpoint_generation: int
    checkpoint_state_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    result_status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    completed_at: datetime
    completion_hash: str
    credential_reference_stored: bool
    upstream_file_content_proof_completed: bool
    upstream_quarantine_staging_completed: bool
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
    command_executed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    storage_copy_performed: bool
    checkpoint_created: bool
    sync_executed: bool
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
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpCheckpointReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    checkpoint_id: UUID
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
    upstream_file_content_proof_completed: bool
    upstream_quarantine_staging_completed: bool
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
    command_executed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    storage_copy_performed: bool
    checkpoint_created: bool
    sync_executed: bool
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
