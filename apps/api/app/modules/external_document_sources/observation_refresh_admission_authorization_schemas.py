from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class _ObservationRefreshAdmissionAuthorizationSafetyRead(BaseModel):
    refresh_execution_verified: bool
    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    current_document_verified: bool
    staged_content_proof_verified: bool
    human_authorization_recorded: bool
    provider_client_constructed: bool
    oauth_token_acquired: bool
    remote_list_performed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    file_signature_validated: bool
    malware_scan_completed: bool
    document_mutated: bool
    evidence_admitted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_sync_started: bool


class ExternalDocumentSourceObservationRefreshAdmissionAuthorizationRead(
    _ObservationRefreshAdmissionAuthorizationSafetyRead
):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    refresh_execution_id: UUID
    refresh_authorization_id: UUID
    decision_id: UUID
    handoff_id: UUID
    binding_id: UUID
    document_family_id: UUID
    expected_prior_document_id: UUID
    expected_prior_version_number: int
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    refresh_authorization_hash: str
    refresh_completion_hash: str
    decision_completion_hash: str
    handoff_completion_hash: str
    binding_completion_hash: str
    observed_projection_hash: str
    observed_version_token_hash: str | None
    prior_document_file_hash: str
    refreshed_content_sha256: str
    refreshed_content_byte_count: int
    refreshed_content_media_type_class: str | None
    refreshed_content_version_token_hash: str | None
    refreshed_content_proof_hash: str
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    authorized_by_id: UUID
    authorization_reason: str
    authorized_at: datetime
    authorization_hash: str

    @field_serializer("authorized_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceiptRead(
    _ObservationRefreshAdmissionAuthorizationSafetyRead
):
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

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
