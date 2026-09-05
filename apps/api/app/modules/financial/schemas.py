from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.financial.models import CostReviewStatus, FinancialFlagStatus, FinancialFlagType


CostDecisionState = Literal["none", "current", "stale"]


class CostReviewDecisionRead(BaseModel):
    id: UUID
    item_key: str
    state_fingerprint: str
    state_version: int
    decision_number: int
    status: CostReviewStatus
    reason: str
    item_snapshot: dict[str, Any]
    reviewed_by_id: UUID | None
    reviewed_at: datetime
    previous_decision_hash: str | None
    decision_hash: str

    model_config = {"from_attributes": True}


class CostItemRead(BaseModel):
    id: UUID
    document_id: UUID
    document_family_id: UUID
    document_version: int
    document_is_current: bool
    document_processing_status: str
    document_malware_scan_status: str
    source_state: Literal["current_usable"]
    document_kind: str
    supplier: str | None
    document_number: str | None
    document_date: date | None
    line_index: int
    description: str
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    amount: Decimal
    currency: str
    category: str | None
    review_status: CostReviewStatus
    item_key: str
    state_fingerprint: str
    state_version: int
    decision_state: CostDecisionState
    latest_review_decision: CostReviewDecisionRead | None
    review_history: list[CostReviewDecisionRead]


class HistoricalCostReviewRead(BaseModel):
    item_key: str
    decision_state: Literal["stale"]
    current_source_available: Literal[False]
    latest_review_decision: CostReviewDecisionRead
    message: str


class FinancialFlagRead(BaseModel):
    id: UUID
    flag_type: FinancialFlagType
    severity: str
    title: str
    explanation: str
    evidence: dict[str, Any] | None
    status: FinancialFlagStatus
    resolution_note: str | None

    model_config = {"from_attributes": True}


class QuoteComparisonRow(BaseModel):
    document_id: UUID
    document_version: int
    supplier: str | None
    quotation_number: str | None
    currency: str | None
    total: Decimal | None
    scope_summary: str | None
    lead_time: str | None
    repair_duration: str | None
    line_items: list[dict[str, Any]]


class ReserveHistoryRead(BaseModel):
    id: UUID
    amount: Decimal
    currency: str
    reason: str
    created_by_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FinancialReviewSummary(BaseModel):
    current_item_count: int
    current_decision_count: int
    stale_decision_count: int
    unreviewed_item_count: int


class FinancialReviewResponse(BaseModel):
    claim_id: UUID
    totals_by_currency: dict[str, Decimal]
    items: list[CostItemRead]
    flags: list[FinancialFlagRead]
    quotations: list[QuoteComparisonRow]
    reserve_history: list[ReserveHistoryRead]
    historical_reviews: list[HistoricalCostReviewRead]
    summary: FinancialReviewSummary


class CostStatusUpdate(BaseModel):
    status: CostReviewStatus
    reason: str = Field(min_length=3, max_length=1000)
    expected_state_fingerprint: str = Field(min_length=64, max_length=64)
    expected_state_version: int = Field(ge=1)
    confirm_re_review: bool = False

    model_config = {"str_strip_whitespace": True}


class FinancialFlagResolve(BaseModel):
    status: FinancialFlagStatus
    note: str = Field(min_length=3, max_length=2000)

    model_config = {"str_strip_whitespace": True}
