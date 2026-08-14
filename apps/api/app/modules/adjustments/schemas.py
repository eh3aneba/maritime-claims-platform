from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class AdjustmentLineUpdate(BaseModel):
    treatment: AdjustmentTreatment
    basis: AdjustmentBasis
    considered_amount: Decimal
    reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=4000)


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
    created_at: datetime
    updated_at: datetime


class AdjustmentStatementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    created_by_id: UUID | None
    reviewed_by_id: UUID | None
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
    review_note: str | None
    content_hash: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[AdjustmentLineResponse]


class AdjustmentListResponse(BaseModel):
    items: list[AdjustmentStatementResponse]
    total: int
