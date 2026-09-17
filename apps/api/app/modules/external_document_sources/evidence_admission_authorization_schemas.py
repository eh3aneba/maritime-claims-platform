from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceEvidenceAdmissionAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceEvidenceAdmissionAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    generation_3_change_detection_execution_id: UUID
    checkpoint_generation_3_execution_id: UUID
    provider_kind: str
    profile_hash: str
    authorized_projection_hash: str
    authorized_display_name_hash: str
    authorized_version_token_hash: str | None
    authorized_byte_size: int | None
    authorized_mime_type_class: str | None
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

    upstream_checkpoint_generation_3_advance_completed: bool
    upstream_generation_3_change_detection_completed: bool
    latest_generation_3_observation_confirmed: bool
    remote_version_current_at_authorization: bool
    human_authorization_recorded: bool
    provider_client_constructed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_created: bool
    evidence_admitted: bool
    content_parsed: bool
    content_extracted: bool
    claim_mutated: bool
    admission_execution_performed: bool
    background_sync_started: bool

    @field_serializer("authorized_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceEvidenceAdmissionAuthorizationReceiptRead(BaseModel):
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

    upstream_checkpoint_generation_3_advance_completed: bool
    upstream_generation_3_change_detection_completed: bool
    latest_generation_3_observation_confirmed: bool
    remote_version_current_at_authorization: bool
    human_authorization_recorded: bool
    provider_client_constructed: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_created: bool
    evidence_admitted: bool
    content_parsed: bool
    content_extracted: bool
    claim_mutated: bool
    admission_execution_performed: bool
    background_sync_started: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
