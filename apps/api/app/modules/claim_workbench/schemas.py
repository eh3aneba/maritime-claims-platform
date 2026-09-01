from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PriorityTier = Literal["routine", "elevated", "urgent", "critical"]


class WorkbenchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: PriorityTier | None = None
    claim_status: str | None = Field(default=None, max_length=80)
    claim_type: str | None = Field(default=None, max_length=80)
    attention_category: str | None = Field(default=None, max_length=100)
    source_type: str | None = Field(default=None, max_length=100)
    handler_id: UUID | None = None
    requires_action: bool | None = None
    overdue_or_due_soon: bool | None = None


class WorkbenchFactor(BaseModel):
    source_type: str
    source_id: UUID
    source_hash: str | None = None
    category: str
    label: str
    weight: int
    priority_hint: PriorityTier
    due_date: date | None = None
    due_semantics: Literal["authoritative_task_due", "candidate_timebar", "none"] = "none"
    href: str


class WorkbenchClaimRow(BaseModel):
    claim_id: UUID
    claim_reference: str
    claim_type: str
    claim_status: str
    handler_id: UUID | None = None
    priority: PriorityTier
    rank_score: int
    ranking_version: str
    rank_hash: str
    requires_action: bool
    nearest_due_date: date | None = None
    nearest_due_semantics: Literal["authoritative_task_due", "candidate_timebar", "none"] = "none"
    factors: list[WorkbenchFactor]
    source_state_time: datetime | None = None


class WorkbenchPage(BaseModel):
    rows: list[WorkbenchClaimRow]
    page: int
    page_size: int
    total: int
    has_more: bool


class WorkbenchMetrics(BaseModel):
    claim_count: int
    critical_count: int
    urgent_count: int
    elevated_count: int
    due_soon_count: int
    missing_evidence_count: int
    conflict_count: int
    financial_flag_count: int
    pending_ai_review_count: int


class WorkbenchDashboard(BaseModel):
    metrics: WorkbenchMetrics
    rows: list[WorkbenchClaimRow]
    ranking_version: str
    operational_triage_only: bool = True
    claim_merits_decision: bool = False
