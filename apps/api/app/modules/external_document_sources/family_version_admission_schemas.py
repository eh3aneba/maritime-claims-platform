from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceFamilyVersionAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class ExternalDocumentSourceFamilyVersionAdmissionAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    successor_change_detection_execution_id: UUID
    successor_versioned_restaging_execution_id: UUID
    document_family_id: UUID
    expected_prior_document_id: UUID
    expected_prior_version_number: int
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    successor_change_completion_hash: str
    candidate_content_proof_hash: str
    candidate_completion_hash: str
    prior_projection_hash: str
    prior_provider_version_hash: str | None
    prior_document_file_hash: str
    authorized_projection_hash: str
    authorized_display_name_hash: str
    authorized_version_token_hash: str | None
    authorized_byte_size: int
    authorized_mime_type_class: str | None
    candidate_content_sha256: str
    candidate_content_byte_count: int
    candidate_storage_object_key_hash: str
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    authorized_by_id: UUID
    authorization_reason: str
    authorized_at: datetime
    authorization_hash: str

    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    staged_candidate_verified: bool
    current_document_verified: bool
    human_authorization_recorded: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    document_mutated: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool
    background_sync_started: bool

    @field_serializer("authorized_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceiptRead(BaseModel):
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

    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    staged_candidate_verified: bool
    current_document_verified: bool
    human_authorization_recorded: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    document_mutated: bool
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


class ExternalDocumentSourceFamilyVersionAdmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    binding_id: UUID
    authorization_id: UUID
    successor_change_detection_execution_id: UUID
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
    successor_change_completion_hash: str
    candidate_content_proof_hash: str
    candidate_completion_hash: str
    prior_projection_hash: str
    prior_provider_version_hash: str | None
    prior_document_file_hash: str
    fresh_observation_execution_id: UUID
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

    authorization_verified: bool
    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    authorization_single_use_consumed: bool
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

    authorization_verified: bool
    durable_family_binding_verified: bool
    stable_source_identity_verified: bool
    authorization_single_use_consumed: bool
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
