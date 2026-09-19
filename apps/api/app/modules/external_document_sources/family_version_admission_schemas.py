from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceFamilyVersionAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceFamilyVersionAdmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    authorization_id: UUID
    generation_3_change_detection_execution_id: UUID
    checkpoint_generation_3_execution_id: UUID
    successor_versioned_restaging_execution_id: UUID
    document_family_id: UUID
    prior_document_id: UUID
    prior_version_number: int
    new_document_id: UUID
    new_version_number: int
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    authorization_hash: str
    authorized_projection_hash: str
    observation_completion_hash: str
    candidate_content_proof_hash: str
    candidate_completion_hash: str
    prior_projection_hash: str
    prior_provider_version_hash: str | None
    prior_document_file_hash: str
    fresh_projection_hash: str
    fresh_display_name_hash: str
    fresh_version_token_hash: str | None
    fresh_byte_size: int
    fresh_mime_type_class: str | None
    staged_content_sha256: str
    staged_content_byte_count: int
    staged_storage_object_key_hash: str
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

    upstream_authorization_verified: bool
    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    authorization_single_use_consumed: bool
    latest_generation_3_observation_confirmed: bool
    fresh_exact_item_metadata_read_performed: bool
    fresh_remote_version_current: bool
    staged_content_integrity_verified: bool
    malware_scan_completed: bool
    canonical_document_write_completed: bool
    new_document_created: bool
    prior_document_superseded: bool
    exactly_one_current_version_established: bool
    later_version_admitted: bool
    remote_list_performed: bool
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

    @field_serializer("executed_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceFamilyVersionAdmissionReceiptRead(BaseModel):
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

    upstream_authorization_verified: bool
    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    authorization_single_use_consumed: bool
    latest_generation_3_observation_confirmed: bool
    fresh_exact_item_metadata_read_performed: bool
    fresh_remote_version_current: bool
    staged_content_integrity_verified: bool
    malware_scan_completed: bool
    canonical_document_write_completed: bool
    new_document_created: bool
    prior_document_superseded: bool
    exactly_one_current_version_established: bool
    later_version_admitted: bool
    remote_list_performed: bool
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

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
