from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExternalDocumentSourceOperatorFamilyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    binding_id: UUID
    claim_id: UUID
    profile_id: UUID
    provider_kind: str
    document_family_id: UUID
    current_document_id: UUID
    current_version_number: int

    schedule_id: UUID | None = None
    schedule_status: str | None = None
    next_due_at: datetime | None = None

    last_observation_id: UUID | None = None
    last_observation_result: str | None = None
    last_observation_completed_at: datetime | None = None

    pending_handoff_id: UUID | None = None
    pending_handoff_kind: str | None = None
    pending_handoff_projected_at: datetime | None = None

    latest_decision_kind: str | None = None
    latest_decision_status: str | None = None
    latest_decided_at: datetime | None = None

    latest_refresh_status: str | None = None
    latest_refresh_completed_at: datetime | None = None
    latest_admission_authorization_status: str | None = None
    latest_admission_status: str | None = None
    latest_admission_executed_at: datetime | None = None

    processing_release_status: str | None = None
    processing_release_required: bool


class ExternalDocumentSourceOperatorProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_id: UUID
    provider_kind: str
    display_name: str
    profile_status: str

    provider_health_status: str | None = None
    provider_health_latency_class: str | None = None
    provider_health_completed_at: datetime | None = None

    active_family_count: int
    pending_handoff_count: int
    processing_release_required_count: int
    next_due_at: datetime | None = None
    last_observation_completed_at: datetime | None = None


class ExternalDocumentSourceOperatorOverviewRead(BaseModel):
    profiles: list[ExternalDocumentSourceOperatorProfileRead]
    families: list[ExternalDocumentSourceOperatorFamilyRead]
