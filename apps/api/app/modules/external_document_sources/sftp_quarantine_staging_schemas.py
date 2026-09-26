from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpQuarantineStagingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpQuarantineStagingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    file_content_proof_id: UUID
    directory_listing_id: UUID
    listing_entry_id: UUID
    session_activation_id: UUID
    credential_reference_binding_id: UUID
    provider_kind: str
    profile_hash: str
    locator_hash: str
    authentication_kind: str
    reference_backend: str
    destination_hostname: str
    destination_port: int
    pinned_host_key_fingerprint: str
    remote_root_path_hash: str
    upstream_scope_hash: str
    upstream_request_hash: str
    upstream_result_hash: str
    listing_entry_hash: str
    read_adapter_kind: str
    expected_content_sha256: str
    expected_content_byte_count: int
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
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
    upstream_file_content_proof_completed: bool
    secret_resolution_performed: bool
    credential_stored: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    host_key_verification_performed: bool
    host_key_verified: bool
    authentication_performed: bool
    authentication_succeeded: bool
    sftp_session_opened: bool
    sftp_session_closed: bool
    remote_content_transiently_observed: bool
    remote_read_performed: bool
    storage_reconciliation_performed: bool
    durable_content_staged: bool
    remote_content_stored: bool
    session_stored: bool
    raw_response_stored: bool
    remote_content_returned: bool
    remote_content_logged: bool
    content_parsed: bool
    content_extracted: bool
    remote_list_performed: bool
    remote_stat_performed: bool
    remote_write_performed: bool
    remote_rename_performed: bool
    remote_delete_performed: bool
    remote_mkdir_performed: bool
    remote_chmod_performed: bool
    remote_chown_performed: bool
    remote_touch_performed: bool
    command_executed: bool
    storage_delete_performed: bool
    storage_copy_performed: bool
    checkpoint_created: bool
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


class ExternalDocumentSourceSftpQuarantineStagingReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    staging_id: UUID
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
    secret_resolution_performed: bool
    credential_stored: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    host_key_verification_performed: bool
    host_key_verified: bool
    authentication_performed: bool
    authentication_succeeded: bool
    sftp_session_opened: bool
    sftp_session_closed: bool
    remote_content_transiently_observed: bool
    remote_read_performed: bool
    storage_reconciliation_performed: bool
    durable_content_staged: bool
    remote_content_stored: bool
    session_stored: bool
    raw_response_stored: bool
    remote_content_returned: bool
    remote_content_logged: bool
    content_parsed: bool
    content_extracted: bool
    remote_list_performed: bool
    remote_stat_performed: bool
    remote_write_performed: bool
    remote_rename_performed: bool
    remote_delete_performed: bool
    remote_mkdir_performed: bool
    remote_chmod_performed: bool
    remote_chown_performed: bool
    remote_touch_performed: bool
    command_executed: bool
    storage_delete_performed: bool
    storage_copy_performed: bool
    checkpoint_created: bool
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
