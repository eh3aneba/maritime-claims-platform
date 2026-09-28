from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    generation3_change_detection_id: UUID
    generation3_checkpoint_advancement_id: UUID
    generation3_restaging_id: UUID
    provider_kind: str
    profile_hash: str
    authorized_projection_hash: str
    authorized_entry_hash: str
    authorized_relative_path_hash: str
    authorized_byte_size: int
    authorized_modified_at: datetime | None
    authorized_metadata_id_hash: str | None
    authorized_content_sha256: str
    authorized_storage_object_key_hash: str
    storage_backend_kind: str
    storage_purpose: str
    checkpoint_state_hash: str
    checkpoint_completion_hash: str
    candidate_content_proof_hash: str
    candidate_completion_hash: str
    observation_completion_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    authorized_by_id: UUID
    authorization_reason: str
    authorized_at: datetime
    authorization_hash: str

    upstream_generation3_checkpoint_completed: bool
    upstream_generation3_observation_completed: bool
    latest_generation3_observation_confirmed: bool
    remote_version_current_at_authorization: bool
    human_authorization_recorded: bool
    credential_stored: bool
    session_stored: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_stat_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_reconciliation_performed: bool
    durable_content_staged: bool
    checkpoint_created: bool
    checkpoint_advanced: bool
    document_created: bool
    evidence_admitted: bool
    content_parsed: bool
    content_extracted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    background_sync_started: bool

    @field_serializer("authorized_modified_at", "authorized_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    authorization_id: UUID
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

    upstream_generation3_checkpoint_completed: bool
    upstream_generation3_observation_completed: bool
    latest_generation3_observation_confirmed: bool
    remote_version_current_at_authorization: bool
    human_authorization_recorded: bool
    credential_stored: bool
    session_stored: bool
    provider_network_performed: bool
    ssh_transport_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_content_transiently_observed: bool
    remote_list_performed: bool
    remote_stat_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_reconciliation_performed: bool
    durable_content_staged: bool
    checkpoint_created: bool
    checkpoint_advanced: bool
    document_created: bool
    evidence_admitted: bool
    content_parsed: bool
    content_extracted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    background_sync_started: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
