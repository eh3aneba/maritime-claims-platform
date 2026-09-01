from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

WebhookEventType = Literal[
    "ai_operations.document_processing",
    "ai_operations.claim_qa_synthesis",
]
DeliveryStatus = Literal["queued", "attempting", "failed", "delivered", "dead_letter"]


class GovernanceWebhookDestinationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    endpoint_url: str = Field(min_length=1, max_length=1000)
    event_types: list[WebhookEventType] = Field(min_length=1, max_length=2)
    enabled: bool = False


class GovernanceWebhookDestinationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=1000)
    event_types: list[WebhookEventType] | None = Field(default=None, min_length=1, max_length=2)
    enabled: bool | None = None


class GovernanceWebhookDestinationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    endpoint_url: str
    enabled: bool
    event_types: list[str]
    secret_version: int
    secret_reference: str
    rotated_at: datetime | None
    previous_secret_valid_until: datetime | None
    last_tested_at: datetime | None
    last_test_status: str | None
    created_at: datetime
    updated_at: datetime
    secret_material_persisted: bool = False


class GovernanceWebhookSecretIssued(BaseModel):
    destination: GovernanceWebhookDestinationView
    signing_secret: str
    secret_version: int
    secret_reference: str
    disclosure: str = "Signing secret is shown once and is not persisted as raw secret material."


class GovernanceWebhookDeliveryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    destination_id: UUID
    source_workflow_type: str
    source_event_id: UUID
    source_revision_hash: str
    event_type: str
    envelope_version: str
    occurred_at: datetime
    envelope: dict
    payload_hash: str
    secret_version: int
    status: DeliveryStatus
    attempt_count: int
    max_attempts: int
    manual_retry_count: int
    next_attempt_at: datetime
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    last_http_status: int | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    content_free: bool = True


class GovernanceWebhookDeliveryPage(BaseModel):
    deliveries: list[GovernanceWebhookDeliveryView]
    page: int
    page_size: int
    total: int
    has_more: bool


class GovernanceWebhookMetrics(BaseModel):
    destination_count: int
    enabled_destination_count: int
    queued_count: int
    attempting_count: int
    failed_count: int
    delivered_count: int
    dead_letter_count: int
    delivery_success_bps: int | None


class GovernanceWebhookDashboard(BaseModel):
    metrics: GovernanceWebhookMetrics
    destinations: list[GovernanceWebhookDestinationView]
    recent_deliveries: list[GovernanceWebhookDeliveryView]
    content_free_outbound_only: bool = True
    inbound_commands_enabled: bool = False
    raw_claim_or_model_content_exposed: bool = False


class GovernanceWebhookSyncResult(BaseModel):
    destinations_scanned: int
    source_events_scanned: int
    deliveries_created: int
    duplicates_skipped: int


class GovernanceWebhookTestResult(BaseModel):
    delivery: GovernanceWebhookDeliveryView
    signing_secret_required_by_receiver: bool = True


class GovernanceWebhookRetryResult(BaseModel):
    delivery: GovernanceWebhookDeliveryView
    explicit_human_retry: bool = True
