from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClaimIntelligenceDecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "edit", "dismiss"]
    note: str = Field(min_length=5, max_length=4000)
    edited_title: str | None = Field(default=None, min_length=3, max_length=240)
    edited_description: str | None = Field(default=None, min_length=5, max_length=8000)
    edited_suggested_action: str | None = Field(default=None, min_length=5, max_length=4000)
    convert_to_task: bool = False

    @model_validator(mode="after")
    def validate_edit(self):
        if self.action == "edit" and not any((self.edited_title, self.edited_description, self.edited_suggested_action)):
            raise ValueError("An edited field is required for an edit decision")
        if self.action == "dismiss" and self.convert_to_task:
            raise ValueError("Dismissed intelligence cannot be converted into a task")
        return self


class ClaimIntelligenceDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    decided_by_id: UUID | None
    converted_task_id: UUID | None
    decision_number: int
    action: str
    edited_title: str | None
    edited_description: str | None
    edited_suggested_action: str | None
    note: str
    previous_decision_hash: str | None
    decision_hash: str
    decided_at: datetime


class ClaimIntelligenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    snapshot_id: UUID
    item_key: str
    category: str
    title: str
    description: str
    severity: str
    urgency_score: int
    evidential_value_score: int
    rank_score: int
    rationale: str
    source_refs: list[dict]
    action_type: str | None
    suggested_action: str | None
    related_entity_type: str | None
    related_entity_id: UUID | None
    item_hash: str
    latest_decision: ClaimIntelligenceDecisionResponse | None = None


class ClaimIntelligenceSnapshotResponse(BaseModel):
    id: UUID
    claim_id: UUID
    generated_by_id: UUID | None
    snapshot_version: int
    engine_version: str
    source_state_hash: str
    snapshot_hash: str
    summary: dict
    generated_at: datetime
    items: list[ClaimIntelligenceItemResponse]


class ClaimIntelligenceDashboardResponse(BaseModel):
    claim_id: UUID
    snapshot: ClaimIntelligenceSnapshotResponse | None
    disclaimer: str


class DomainCatalogComponentResponse(BaseModel):
    code: str
    title: str


class DomainCatalogIncidentResponse(BaseModel):
    code: str
    title: str
    description: str
    component_codes: list[str]
    contextual_rule_ids: list[str]


class ClaimDomainCatalogResponse(BaseModel):
    catalog_version: str
    non_authoritative: bool
    human_classification_required: bool
    automatic_claim_decision: bool
    incidents: list[DomainCatalogIncidentResponse]
    machinery_components: list[DomainCatalogComponentResponse]


class ClaimDomainClassificationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_code: str = Field(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    component_code: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    failure_mode: str | None = Field(default=None, min_length=3, max_length=160)
    note: str = Field(min_length=20, max_length=2000)
    confirm_classification: bool = False


class ClaimDomainClassificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    catalog_version: str
    classification_number: int
    incident_code: str
    component_code: str | None
    failure_mode: str | None
    classification_note: str
    classified_by_id: UUID | None
    supersedes_classification_id: UUID | None
    previous_classification_hash: str | None
    classification_hash: str
    created_at: datetime


class DomainPlaybookDefinitionResponse(BaseModel):
    incident_code: str
    title: str
    objective: str
    investigation_tracks: list[str]
    evidence_prompts: list[str]
    review_topics: list[str]
    contextual_rule_ids: list[str]


class DomainPlaybookSourceRefResponse(BaseModel):
    kind: Literal["claim_domain_classification"]
    id: UUID
    catalog_version: str
    classification_number: int
    classification_hash: str


class DomainPlaybookClassificationContextResponse(BaseModel):
    incident_code: str
    incident_title: str
    component_code: str | None
    component_title: str | None
    failure_mode: str | None


class ClaimDomainPlaybookPreviewResponse(BaseModel):
    registry_version: str
    registry_hash: str
    classification_required: bool
    non_authoritative: bool
    read_only_preview: bool
    automatic_rule_execution: bool
    automatic_requirement_activation: bool
    automatic_task_creation: bool
    automatic_claim_decision: bool
    authority_boundary: str
    source_ref: DomainPlaybookSourceRefResponse | None
    classification_context: DomainPlaybookClassificationContextResponse | None
    playbook: DomainPlaybookDefinitionResponse | None


class ClaimInvestigationPlanWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry_version: str = Field(min_length=3, max_length=32)
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification_id: UUID
    classification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    investigation_tracks: list[str] = Field(default_factory=list, max_length=12)
    evidence_prompts: list[str] = Field(default_factory=list, max_length=20)
    review_topics: list[str] = Field(default_factory=list, max_length=12)
    note: str = Field(min_length=20, max_length=2000)
    confirm_adoption: bool = False

    @model_validator(mode="after")
    def validate_selection(self):
        selections = self.investigation_tracks + self.evidence_prompts + self.review_topics
        if not selections:
            raise ValueError("At least one canonical playbook item must be selected")
        for values in (self.investigation_tracks, self.evidence_prompts, self.review_topics):
            if len(values) != len(set(values)):
                raise ValueError("Investigation plan selections cannot contain duplicates")
        return self


class ClaimInvestigationPlanResponse(BaseModel):
    id: UUID
    claim_id: UUID
    plan_number: int
    classification_id: UUID
    catalog_version: str
    classification_number: int
    classification_hash: str
    registry_version: str
    registry_hash: str
    incident_code: str
    component_code: str | None
    failure_mode: str | None
    investigation_tracks: list[str]
    evidence_prompts: list[str]
    review_topics: list[str]
    contextual_rule_ids: list[str]
    adoption_note: str
    adopted_by_id: UUID | None
    supersedes_plan_id: UUID | None
    previous_plan_hash: str | None
    adoption_key_hash: str
    plan_hash: str
    adopted_at: datetime
    source_current: bool
    non_authoritative: bool = True
    automatic_rule_execution: bool = False
    automatic_requirement_activation: bool = False
    automatic_task_creation: bool = False
    automatic_claim_decision: bool = False
