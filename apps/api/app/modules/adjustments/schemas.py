from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.adjustments.models import AdjustmentBasis, AdjustmentStatus, AdjustmentTreatment


class AdjustmentCreate(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    title: str | None = Field(default=None, max_length=240)


class AdjustmentStatementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=240)
    deductible_amount: Decimal | None = Field(default=None, ge=0)
    deductible_basis: str | None = Field(default=None, max_length=2000)
    other_deduction_amount: Decimal | None = Field(default=None, ge=0)
    other_deduction_basis: str | None = Field(default=None, max_length=2000)


class SourceGroundedAdjustmentControl(BaseModel):
    amount: Decimal | None = Field(default=None, ge=0)
    percentage: Decimal | None = Field(default=None, ge=0, le=100)
    basis: str = Field(min_length=3, max_length=2000)
    source_reference: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def require_value(self):
        if self.amount is None and self.percentage is None:
            raise ValueError("A structured adjustment control requires an amount or percentage.")
        return self


class FXControl(BaseModel):
    rate: Decimal = Field(gt=0)
    source_currency: str = Field(min_length=3, max_length=3)
    target_currency: str = Field(min_length=3, max_length=3)
    rate_date: date
    source_reference: str = Field(min_length=3, max_length=2000)


class LineFinancialControls(BaseModel):
    fx: FXControl | None = None
    tax: SourceGroundedAdjustmentControl | None = None
    depreciation: SourceGroundedAdjustmentControl | None = None
    betterment: SourceGroundedAdjustmentControl | None = None
    allocation: SourceGroundedAdjustmentControl | None = None


class AdjustmentLineUpdate(BaseModel):
    treatment: AdjustmentTreatment
    basis: AdjustmentBasis
    considered_amount: Decimal
    claimed_amount: Decimal | None = Field(default=None, ge=0)
    financial_controls: LineFinancialControls | None = None
    reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=4000)


class AdjustmentRebase(BaseModel):
    carry_statement_controls: bool = False
    note: str = Field(min_length=3, max_length=2000)


class AdjustmentReview(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class AdjustmentLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    statement_id: UUID
    cost_item_id: UUID | None
    source_document_id: UUID | None
    sort_order: int
    description: str
    supplier: str | None
    document_number: str | None
    category: str | None
    claimed_amount: Decimal
    considered_amount: Decimal
    treatment: AdjustmentTreatment
    basis: AdjustmentBasis
    reason: str | None
    note: str | None
    source_snapshot: dict
    financial_controls: dict
    created_at: datetime
    updated_at: datetime


class AdjustmentStatementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    created_by_id: UUID | None
    reviewed_by_id: UUID | None
    rebased_from_statement_id: UUID | None
    version: int
    title: str
    currency: str
    status: AdjustmentStatus
    deductible_amount: Decimal
    deductible_basis: str | None
    other_deduction_amount: Decimal
    other_deduction_basis: str | None
    gross_claimed: Decimal
    gross_considered: Decimal
    net_adjusted: Decimal
    source_manifest: list
    source_manifest_version: int
    source_state_hash: str | None
    current_source_state_hash: str | None
    source_state_status: str
    source_change_summary: dict
    review_note: str | None
    content_hash: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[AdjustmentLineResponse]


class AdjustmentListResponse(BaseModel):
    items: list[AdjustmentStatementResponse]
    total: int
