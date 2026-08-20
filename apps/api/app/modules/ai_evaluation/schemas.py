from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AIEvaluationSuiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activation_request_id: UUID
    suite_key: str = Field(min_length=8, max_length=120)
    confirm_content_free: bool


class AIEvaluationCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_key: str = Field(min_length=5, max_length=120)
    document_type: Literal["chief_engineer_report", "engine_log"]
    scenario_type: Literal[
        "baseline", "prompt_injection", "malformed_input", "cross_tenant", "restricted_data"
    ]
    data_mode: Literal["synthetic", "deidentified"]
    result: Literal["pass", "fail"]
    field_true_positive: int = Field(ge=0, le=1_000_000)
    field_false_positive: int = Field(ge=0, le=1_000_000)
    field_false_negative: int = Field(ge=0, le=1_000_000)
    extracted_claim_count: int = Field(ge=0, le=1_000_000)
    unsupported_claim_count: int = Field(ge=0, le=1_000_000)
    source_quote_checked_count: int = Field(ge=0, le=1_000_000)
    source_quote_valid_count: int = Field(ge=0, le=1_000_000)
    human_approved_count: int = Field(ge=0, le=1_000_000)
    human_edited_count: int = Field(ge=0, le=1_000_000)
    human_rejected_count: int = Field(ge=0, le=1_000_000)
    latency_ms: int = Field(ge=1, le=600_000)
    input_tokens: int = Field(ge=0, le=2_000_000)
    output_tokens: int = Field(ge=0, le=2_000_000)
    observed_provider_cost_microusd: int = Field(ge=0, le=100_000_000)
    boundary_control_passed: bool
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    executed_at: datetime
    confirm_content_free: bool


class AIEvaluationFinalize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_finalize: bool
    note: str = Field(min_length=10, max_length=4000)


class AIEvaluationReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_role: Literal["quality", "risk"]
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIEvaluationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["promote_staging", "hold"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AIEvaluationRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_revoke: bool
    note: str = Field(min_length=10, max_length=4000)


class AIEvaluationCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    suite_id: UUID
    submitted_by_id: UUID | None
    case_key: str
    document_type: str
    scenario_type: str
    data_mode: str
    result: str
    field_true_positive: int
    field_false_positive: int
    field_false_negative: int
    extracted_claim_count: int
    unsupported_claim_count: int
    source_quote_checked_count: int
    source_quote_valid_count: int
    human_approved_count: int
    human_edited_count: int
    human_rejected_count: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    observed_provider_cost_microusd: int
    boundary_control_passed: bool
    evidence_reference: str
    note: str
    result_hash: str
    executed_at: datetime
    created_at: datetime


class AIEvaluationReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    suite_id: UUID
    reviewer_id: UUID | None
    review_role: str
    action: str
    evidence_reference: str | None
    note: str
    reviewed_at: datetime
    created_at: datetime


class AIEvaluationSuiteResponse(BaseModel):
    id: UUID
    activation_request_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    revoked_by_id: UUID | None
    attempt_number: int
    suite_key: str
    benchmark_profile: str
    activation_model: str
    prompt_bundle_version: str
    schema_bundle_version: str
    max_input_chars: int
    max_output_tokens: int
    data_mode: str
    thresholds: dict
    status: str
    outcome: str | None
    metrics: dict | None
    failure_reasons: list[str]
    evaluation_hash: str | None
    evaluation_note: str | None
    evaluated_at: datetime | None
    decision_note: str | None
    decision_hash: str | None
    decided_at: datetime | None
    promotion_expires_at: datetime | None
    revoked_at: datetime | None
    revocation_note: str | None
    summary: dict
    cases: list[AIEvaluationCaseResponse]
    reviews: list[AIEvaluationReviewResponse]
    created_at: datetime


class AIEvaluationDashboard(BaseModel):
    suites: list[AIEvaluationSuiteResponse]
