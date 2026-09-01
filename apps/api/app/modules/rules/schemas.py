from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.rules.models import IssueCategory, IssueSeverity, IssueStatus, RequirementPriority, RequirementStatus


class DocumentRequirementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rule_id: str
    rule_version: str
    document_type: str
    document_label: str
    priority: RequirementPriority
    required_from_status: str
    reason: str
    status: RequirementStatus
    matched_document_id: UUID | None
    equivalent_claim_fact_id: UUID | None
    satisfaction_basis: str | None
    satisfaction_note: str | None
    satisfied_by_id: UUID | None
    satisfied_at: datetime | None
    equivalent_evidence_candidates: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool
    last_evaluated_at: datetime | None


class ClaimIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    issue_key: str
    rule_id: str
    rule_version: str
    category: IssueCategory
    title: str
    description: str
    severity: IssueSeverity
    status: IssueStatus
    evidence: dict | None
    explanation: str | None
    is_active: bool
    last_triggered_at: datetime | None


class MarineRuleEvaluationResponse(BaseModel):
    rule_id: str
    rule_version: str
    definition_hash: str
    family: str
    topic: str
    source_title: str
    source_reference: str
    status: str
    evidence_used: list[dict[str, Any]] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    rationale: str
    candidate_implication: str
    recommended_action: str
    evaluation_hash: str


class ReadinessResponse(BaseModel):
    score: int
    state: str
    critical_missing_count: int
    important_missing_count: int
    blocking_items: list[str]
    satisfied_weight: int
    total_weight: int


class RuleSummaryResponse(BaseModel):
    ruleset_name: str
    ruleset_version: str
    claim_id: UUID
    evaluated_at: datetime | None
    requirements: list[DocumentRequirementResponse]
    issues: list[ClaimIssueResponse]
    readiness: ReadinessResponse
    triggered_rule_ids: list[str]
    marine_registry_version: str | None = None
    marine_registry_hash: str | None = None
    marine_rule_evaluations: list[MarineRuleEvaluationResponse] = Field(default_factory=list)
    marine_rule_counts: dict[str, int] = Field(default_factory=dict)
    marine_evaluated_at: datetime | None = None
    marine_rule_run_id: UUID | None = None
    human_authority_boundary: str | None = None


class RuleEvaluationResponse(BaseModel):
    run_id: UUID
    marine_run_id: UUID | None = None
    summary: RuleSummaryResponse


class EquivalentEvidenceRequest(BaseModel):
    claim_fact_id: UUID
    note: str


class EquivalentEvidenceResponse(BaseModel):
    requirement: DocumentRequirementResponse
