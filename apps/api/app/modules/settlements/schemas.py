from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.settlements.models import PaymentStatus, SettlementStatus, SettlementType


class SettlementCreate(BaseModel):
    adjustment_statement_id: UUID
    title: str = Field(min_length=3, max_length=240)
    settlement_type: SettlementType
    amount: Decimal = Field(gt=0)
    terms: str = Field(min_length=3, max_length=12000)
    release_required: bool = True
    without_prejudice: bool = True
    expires_on: date | None = None


class SettlementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=240)
    settlement_type: SettlementType | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    terms: str | None = Field(default=None, min_length=3, max_length=12000)
    release_required: bool | None = None
    without_prejudice: bool | None = None
    expires_on: date | None = None


class ReviewNote(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class DispositionRecord(BaseModel):
    disposition: str
    note: str = Field(min_length=3, max_length=2000)


class PaymentCreate(BaseModel):
    settlement_id: UUID
    payee: str = Field(min_length=2, max_length=240)
    amount: Decimal = Field(gt=0)
    purpose: str = Field(min_length=3, max_length=4000)


class PaidRecord(BaseModel):
    confirm_paid_externally: bool
    channel: str = Field(min_length=2, max_length=60)
    external_reference: str = Field(min_length=3, max_length=240)
    value_date: date
    note: str | None = Field(default=None, max_length=2000)


class SettlementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    adjustment_statement_id: UUID
    created_by_id: UUID | None
    reviewed_by_id: UUID | None
    disposition_by_id: UUID | None
    version: int
    title: str
    settlement_type: SettlementType
    status: SettlementStatus
    currency: str
    amount: Decimal
    terms: str
    release_required: bool
    without_prejudice: bool
    expires_on: date | None
    source_adjustment_hash: str
    source_snapshot: dict
    review_note: str | None
    disposition_note: str | None
    content_hash: str | None
    reviewed_at: datetime | None
    disposition_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    settlement_id: UUID
    created_by_id: UUID | None
    first_approved_by_id: UUID | None
    second_approved_by_id: UUID | None
    paid_recorded_by_id: UUID | None
    sequence: int
    status: PaymentStatus
    payee: str
    currency: str
    amount: Decimal
    purpose: str
    first_approval_note: str | None
    second_approval_note: str | None
    rejection_note: str | None
    content_hash: str | None
    first_approved_at: datetime | None
    second_approved_at: datetime | None
    paid_channel: str | None
    external_reference: str | None
    value_date: date | None
    paid_note: str | None
    paid_recorded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SettlementLedgerResponse(BaseModel):
    settlements: list[SettlementResponse]
    payments: list[PaymentResponse]
