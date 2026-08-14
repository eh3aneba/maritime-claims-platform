from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


PolicyIssueSeverity = Literal["info", "low", "medium", "high", "critical"]


class PolicyTermSource(BaseModel):
    document_id: UUID
    document_family_id: UUID
    document_name: str
    document_type: str | None
    document_version: int
    document_is_current: bool
    source_locator_type: str | None
    source_locator_value: str | None
    source_quote: str | None
    source_verified: bool


class ReviewedPolicyTerm(BaseModel):
    extraction_id: UUID
    category: str
    title: str
    value: Any
    human_status: str
    confidence: str
    reviewed_at: datetime | None
    source: PolicyTermSource


class PolicyIssueSpot(BaseModel):
    code: str
    severity: PolicyIssueSeverity
    title: str
    description: str
    trigger: dict[str, Any]
    required_human_action: str
    related_extraction_ids: list[UUID]


class PolicyIntelligenceSummary(BaseModel):
    reviewed_term_count: int
    current_policy_document_count: int
    historical_policy_document_count: int
    issue_count: int
    high_priority_issue_count: int
    has_policy_period: bool
    has_insured_value_or_limit: bool
    has_deductible: bool


class PolicyIntelligenceResponse(BaseModel):
    claim_id: UUID
    generated_at: datetime
    terms: list[ReviewedPolicyTerm]
    issue_spots: list[PolicyIssueSpot]
    summary: PolicyIntelligenceSummary
    disclaimer: str


class PolicyExtractionCandidate(BaseModel):
    extraction_id: UUID
    field_path: str
    category: str
    title: str
    value: Any
    confidence: str
    source_locator_type: str | None
    source_locator_value: str | None
    source_quote: str
    human_status: str


class PolicyExtractionResponse(BaseModel):
    run_id: UUID
    claim_id: UUID
    document_id: UUID
    document_name: str
    candidate_count: int
    candidates: list[PolicyExtractionCandidate]
    review_required: bool = True
    external_ai_used: bool = False
