from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

WorkflowType = Literal["document_processing", "claim_qa_synthesis"]
HumanReviewState = Literal["pending", "completed", "not_applicable"]
ExportFormat = Literal["json", "csv"]


class AIOperationsFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_type: WorkflowType | None = None
    claim_id: UUID | None = None
    document_id: UUID | None = None
    document_type: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=80)
    human_review_state: HumanReviewState | None = None
    human_review_action: Literal["approve", "edit", "reject"] | None = None
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    authorization_id: UUID | None = None
    failure_code: str | None = Field(default=None, max_length=120)
    created_from: datetime | None = None
    created_to: datetime | None = None
    requires_attention: bool | None = None


class AIOperationsEvent(BaseModel):
    id: UUID
    workflow_type: WorkflowType
    event_time: datetime
    claim_id: UUID
    document_id: UUID | None = None
    document_type: str | None = None
    authorization_id: UUID | None = None
    authorization_hash: str | None = None
    eligibility_decision_id: UUID | None = None
    eligibility_policy_hash: str | None = None
    eligibility_decision_hash: str | None = None
    status: str
    failure_code: str | None = None
    fallback_used: bool
    provider_call_made: bool
    provider: str | None = None
    model: str | None = None
    prompt_bundle_version: str | None = None
    schema_bundle_version: str | None = None
    human_review_state: HumanReviewState
    human_review_action: str | None = None
    requested_by_id: UUID | None = None
    reviewed_by_id: UUID | None = None
    run_hash: str | None = None
    review_hash: str | None = None
    retrieval_run_id: UUID | None = None
    question_hash: str | None = None
    result_set_hash: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    answer_hash: str | None = None
    source_count: int | None = None
    output_candidate_count: int | None = None
    human_edit_count: int | None = None
    unsupported_output_count: int | None = None
    source_grounded_output_count: int | None = None
    source_grounding_total_count: int | None = None
    input_chars: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    observed_provider_cost_microusd: int | None = None
    requires_attention: bool
    attention_reasons: list[str]
    content_free: bool = True


class AIOperationsPage(BaseModel):
    events: list[AIOperationsEvent]
    page: int
    page_size: int
    total: int
    has_more: bool


class AIOperationsMetrics(BaseModel):
    event_count: int
    document_processing_count: int
    claim_qa_synthesis_count: int
    provider_run_count: int
    blocked_or_fallback_count: int
    verification_failure_count: int
    authorization_or_policy_block_count: int
    pending_human_review_count: int
    approve_count: int
    edit_count: int
    reject_count: int
    unsupported_output_count: int
    source_grounding_validity_bps: int | None
    total_tokens: int
    total_observed_provider_cost_microusd: int
    mean_latency_ms: int | None
    p95_latency_ms: int | None
    requires_attention_count: int
    failures_by_workflow: dict[str, int]
    failures_by_model: dict[str, int]


class AIOperationsDashboard(BaseModel):
    metrics: AIOperationsMetrics
    recent_attention: list[AIOperationsEvent]
    content_free_governance_plane: bool = True
    raw_claim_or_model_content_exposed: bool = False


class AIOperationsIncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["privacy", "security", "quality", "cost", "availability", "cross_tenant", "reliability", "other"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_incident_handoff: bool


class AIOperationsExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: ExportFormat
    filters: AIOperationsFilters = Field(default_factory=AIOperationsFilters)
    max_rows: int = Field(default=5000, ge=1, le=10000)
