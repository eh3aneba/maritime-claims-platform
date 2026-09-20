from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


ObservationReviewDecisionKind = Literal[
    "approve_refresh",
    "dismiss",
    "acknowledge_missing",
]


class ExternalDocumentSourceObservationReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    decision_kind: ObservationReviewDecisionKind
    reason: str = Field(min_length=20, max_length=2000)


class _DecisionSafetyRead(BaseModel):
    handoff_integrity_verified: bool
    current_authority_verified: bool
    current_document_verified: bool
    human_decision_recorded: bool
    service_identity_used_as_human: bool
    provider_client_constructed: bool
    token_acquired: bool
    remote_list_performed: bool
    remote_metadata_read_performed: bool
    remote_content_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    storage_read_performed: bool
    storage_write_performed: bool
    storage_delete_performed: bool
    document_mutated: bool
    evidence_admitted: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    checkpoint_advanced: bool


class ExternalDocumentSourceObservationReviewDecisionRead(_DecisionSafetyRead):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    handoff_id: UUID
    observation_execution_id: UUID
    schedule_id: UUID
    binding_id: UUID
    document_family_id: UUID
    current_document_id: UUID
    current_version_number: int
    current_document_file_hash: str

    result_status: str
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    handoff_completion_hash: str
    binding_completion_hash: str
    prior_projection_hash: str
    prior_provider_version_hash: str | None
    observed_projection_hash: str | None
    observed_version_token_hash: str | None

    request_key: str
    decision_kind: str
    status: str
    decided_by_id: UUID
    decision_reason: str
    decided_at: datetime
    scope_hash: str
    request_hash: str
    completion_hash: str

    @field_serializer("decided_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceObservationReviewDecisionReceiptRead(_DecisionSafetyRead):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    decision_id: UUID
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


class ExternalDocumentSourceObservationRefreshAuthorizationRead(_DecisionSafetyRead):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    profile_id: UUID
    handoff_id: UUID
    decision_id: UUID
    binding_id: UUID
    document_family_id: UUID
    current_document_id: UUID
    current_version_number: int
    current_document_file_hash: str

    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str
    handoff_completion_hash: str
    decision_completion_hash: str
    binding_completion_hash: str
    result_status: str
    prior_projection_hash: str
    prior_provider_version_hash: str | None
    observed_projection_hash: str
    observed_version_token_hash: str | None

    execution_limit: int
    status: str
    authorized_by_id: UUID
    authorized_at: datetime
    scope_hash: str
    authorization_hash: str

    @field_serializer("authorized_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
