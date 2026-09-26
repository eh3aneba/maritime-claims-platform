from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpChangeDetectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpChangeDetectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    checkpoint_id: UUID
    directory_listing_id: UUID
    listing_entry_id: UUID
    credential_reference_binding_id: UUID
    provider_kind: str
    profile_hash: str
    checkpoint_state_hash: str
    checkpoint_completion_hash: str
    baseline_entry_hash: str
    baseline_relative_path_hash: str
    baseline_entry_kind: str
    baseline_byte_size: int | None
    baseline_modified_at: datetime | None
    baseline_metadata_id_hash: str | None
    observation_operation_kind: str
    observation_adapter_kind: str
    observation_policy_hash: str
    authentication_method: str
    latency_class: str
    observed_projection_hash: str | None
    observed_entry_kind: str | None
    observed_byte_size: int | None
    observed_modified_at: datetime | None
    observed_metadata_id_hash: str | None
    changed_dimensions: str | None
    request_key: str
    scope_hash: str
    request_hash: str
    result_status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    completed_at: datetime
    completion_hash: str
    credential_reference_stored: bool
    upstream_checkpoint_completed: bool
    secret_resolution_performed: bool
    credential_stored: bool
    session_stored: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    host_key_verification_performed: bool
    host_key_verified: bool
    authentication_performed: bool
    authentication_succeeded: bool
    sftp_session_opened: bool
    sftp_session_closed: bool
    exact_item_metadata_read_performed: bool
    change_detection_completed: bool
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
    storage_delete_performed: bool
    storage_copy_performed: bool
    checkpoint_advanced: bool
    subscription_created: bool
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

    @field_serializer("baseline_modified_at", "observed_modified_at", "requested_at", "completed_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpChangeDetectionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    execution_id: UUID
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
    secret_resolution_performed: bool
    credential_stored: bool
    session_stored: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    host_key_verification_performed: bool
    host_key_verified: bool
    authentication_performed: bool
    authentication_succeeded: bool
    sftp_session_opened: bool
    sftp_session_closed: bool
    exact_item_metadata_read_performed: bool
    change_detection_completed: bool
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
    storage_delete_performed: bool
    storage_copy_performed: bool
    checkpoint_advanced: bool
    subscription_created: bool
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
