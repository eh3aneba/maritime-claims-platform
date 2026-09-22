from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceObservationRefreshAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class _ObservationRefreshAdmissionExecutionSafetyRead(BaseModel):
    authorization_verified: bool
    refresh_execution_verified: bool
    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    authorization_single_use_consumed: bool
    current_document_verified: bool
    staged_storage_read_performed: bool
    staged_content_integrity_verified: bool
    file_signature_validated: bool
    malware_scan_completed: bool
    canonical_document_write_completed: bool
    new_document_created: bool
    prior_document_superseded: bool
    exactly_one_current_version_established: bool
    refreshed_version_admitted: bool
    provider_client_constructed: bool
    oauth_token_acquired: bool
    remote_list_performed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    staged_storage_write_performed: bool
    staged_storage_delete_performed: bool
    content_parsed: bool
    content_extracted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_sync_started: bool


class ExternalDocumentSourceObservationRefreshAdmissionRead(
    _ObservationRefreshAdmissionExecutionSafetyRead
):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    authorization_id: UUID
    refresh_execution_id: UUID
    document_family_id: UUID
    prior_document_id: UUID
    prior_version_number: int
    new_document_id: UUID
    new_version_number: int
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    authorization_hash: str
    refresh_completion_hash: str
    binding_completion_hash: str
    prior_document_file_hash: str
    refreshed_content_proof_hash: str
    refreshed_content_sha256: str
    refreshed_content_byte_count: int
    refreshed_content_media_type_class: str | None
    refreshed_content_version_token_hash: str | None
    staged_storage_backend_kind: str
    staged_storage_purpose: str
    staged_storage_object_key_hash: str
    validated_file_suffix: str
    malware_scan_verdict: str
    security_verification_hash: str
    new_document_file_hash: str
    new_document_file_size_bytes: int
    new_document_filename_hash: str
    canonical_storage_key_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    executed_by_id: UUID
    execution_reason: str
    executed_at: datetime
    completion_hash: str

    @field_serializer("executed_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceObservationRefreshAdmissionReceiptRead(
    _ObservationRefreshAdmissionExecutionSafetyRead
):
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

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
