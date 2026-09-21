from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceObservationRefreshExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=20, max_length=2000)


class _RefreshSafetyRead(BaseModel):
    authorization_integrity_verified: bool
    current_authority_verified: bool
    current_document_verified: bool
    provider_lineage_verified: bool
    originating_observation_verified: bool
    provider_client_constructed: bool
    exact_item_content_read_performed: bool
    storage_write_performed: bool
    storage_read_performed: bool
    durable_content_staged: bool
    remote_list_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_delete_performed: bool
    provider_response_body_stored: bool
    remote_content_returned: bool
    content_parsed: bool
    content_extracted: bool
    document_mutated: bool
    evidence_admitted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool


class ExternalDocumentSourceObservationRefreshExecutionRead(_RefreshSafetyRead):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    authorization_id: UUID
    decision_id: UUID
    handoff_id: UUID
    observation_execution_id: UUID
    binding_id: UUID
    document_family_id: UUID
    current_document_id: UUID
    current_version_number: int
    current_document_file_hash: str
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    authorization_hash: str
    decision_completion_hash: str
    handoff_completion_hash: str
    binding_completion_hash: str
    observed_projection_hash: str
    observed_version_token_hash: str | None
    read_operation_kind: str
    read_adapter_kind: str
    endpoint_policy_hash: str
    storage_backend_kind: str
    storage_purpose: str
    storage_object_key_hash: str
    content_sha256: str
    content_byte_count: int
    content_media_type_class: str | None
    content_version_token_hash: str | None
    content_proof_hash: str
    request_key: str
    request_hash: str
    scope_hash: str
    status: str
    result_status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    completed_at: datetime
    completion_hash: str

    @field_serializer("requested_at", "completed_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceObservationRefreshReceiptRead(_RefreshSafetyRead):
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
