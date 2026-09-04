from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.rules.models import IssueCategory, IssueSeverity, IssueStatus, RequirementPriority, RequirementStatus


class RequirementDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    requirement_id: UUID
    decided_by_id: UUID | None
    claim_fact_id: UUID | None
    state_fingerprint: str
    state_version: int
    decision_number: int
    action: str
    note: str
    claim_fact_version: int | None
    source_document_id: UUID | None
    source_document_version: int | None
    previous_decision_hash: str | None
    decision_hash: str
    decided_at: datetime


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
    state_fingerprint: str | None = None
    state_version: int | None = None
    latest_decision: RequirementDecisionResponse | None = None
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


class MarineRuleDecisionWrite(BaseModel):
    evaluation_hash: str = Field(min_length=64, max_length=64)
    action: Literal["accept", "edit", "dismiss", "not_applicable"]
    note: str = Field(min_length=5, max_length=4000)
    edited_candidate_implication: str | None = Field(default=None, max_length=8000)
    edited_recommended_action: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def validate_edit_payload(self):
        has_edit = bool(self.edited_candidate_implication or self.edited_recommended_action)
        if self.action == "edit" and not has_edit:
            raise ValueError("Edit decisions require an edited candidate implication or recommended action.")
        if self.action != "edit" and has_edit:
            raise ValueError("Edited wording is only permitted when action is edit.")
        return self


class MarineRuleDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rule_run_id: UUID
    decided_by_id: UUID | None
    rule_id: str
    rule_version: str
    evaluation_hash: str
    decision_number: int
    action: str
    note: str
    edited_candidate_implication: str | None
    edited_recommended_action: str | None
    previous_decision_hash: str | None
    decision_hash: str
    decided_at: datetime


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
    latest_decision: MarineRuleDecisionResponse | None = None


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
    claim_fact_version: int = Field(ge=1)
    expected_state_fingerprint: str = Field(min_length=64, max_length=64)
    expected_state_version: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=4000)
    re_review: bool = False


class EquivalentEvidenceResponse(BaseModel):
    requirement: DocumentRequirementResponse
    decision: RequirementDecisionResponse


class RequirementDecisionHistoryResponse(BaseModel):
    requirement_id: UUID
    state_fingerprint: str
    state_version: int
    items: list[RequirementDecisionResponse] = Field(default_factory=list)
