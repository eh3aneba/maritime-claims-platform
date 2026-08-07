from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field
from app.modules.financial.models import CostReviewStatus, FinancialFlagStatus, FinancialFlagType

class CostItemRead(BaseModel):
    id: UUID
    document_id: UUID
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

class FinancialFlagRead(BaseModel):
    id: UUID
    flag_type: FinancialFlagType
    severity: str
    title: str
    explanation: str
    evidence: dict[str, Any] | None
    status: FinancialFlagStatus
    resolution_note: str | None

class QuoteComparisonRow(BaseModel):
    document_id: UUID
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

class FinancialReviewResponse(BaseModel):
    claim_id: UUID
    totals_by_currency: dict[str, Decimal]
    items: list[CostItemRead]
    flags: list[FinancialFlagRead]
    quotations: list[QuoteComparisonRow]
    reserve_history: list[ReserveHistoryRead]

class CostStatusUpdate(BaseModel):
    status: CostReviewStatus
    reason: str = Field(min_length=3,max_length=1000)

class FinancialFlagResolve(BaseModel):
    status: FinancialFlagStatus
    note: str = Field(min_length=3,max_length=2000)
