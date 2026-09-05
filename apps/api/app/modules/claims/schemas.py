from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.claims.models import ClaimPriority, ClaimStatus, ClaimSubtype, ClaimType
from app.modules.users.models import UserRole


class VesselBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    imo_number: str | None


class HandlerBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str
    role: UserRole


class ClaimCreate(BaseModel):
    vessel_id: UUID
    incident_date: date
    notification_date: date
    incident_description: str = Field(min_length=10, max_length=10000)
    claim_type: ClaimType = ClaimType.HULL_MACHINERY
    claim_subtype: ClaimSubtype = ClaimSubtype.MACHINERY_DAMAGE
    priority: ClaimPriority = ClaimPriority.MEDIUM
    external_reference: str | None = Field(default=None, max_length=100)
    estimated_loss: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    handler_id: UUID | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class ClaimUpdate(BaseModel):
    vessel_id: UUID | None = None
    incident_date: date | None = None
    notification_date: date | None = None
    incident_description: str | None = Field(default=None, min_length=10, max_length=10000)
    external_reference: str | None = Field(default=None, max_length=100)
    estimated_loss: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    priority: ClaimPriority | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class ClaimAssign(BaseModel):
    handler_id: UUID | None


class ClaimStatusChange(BaseModel):
    status: ClaimStatus
    reason: str | None = Field(default=None, max_length=1000)


ReserveSourceKind = Literal["manual", "reserve_support", "adjustment"]


class ClaimReserveChange(BaseModel):
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    expected_reserve_version: int = Field(ge=0)
    expected_reserve_hash: str | None = Field(default=None, min_length=64, max_length=64)
    source_kind: ReserveSourceKind = "manual"
    source_reference_id: UUID | None = None

    model_config = {"str_strip_whitespace": True}

    @model_validator(mode="after")
    def validate_source_reference(self):
        if self.source_kind == "manual" and self.source_reference_id is not None:
            raise ValueError("Manual reserve changes must not identify an upstream financial source")
        if self.source_kind != "manual" and self.source_reference_id is None:
            raise ValueError("A source_reference_id is required for reserve_support or adjustment provenance")
        if self.expected_reserve_version == 0 and self.expected_reserve_hash is not None:
            raise ValueError("expected_reserve_hash must be omitted when expected_reserve_version is 0")
        if self.expected_reserve_version > 0 and self.expected_reserve_hash is None:
            raise ValueError("expected_reserve_hash is required when expected_reserve_version is greater than 0")
        return self


class ReserveHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal
    currency: str
    reason: str
    created_by_id: UUID | None
    created_at: datetime
    sequence: int | None
    idempotency_key: str | None
    source_kind: str
    source_reference_id: UUID | None
    source_state_hash: str | None
    source_snapshot: dict[str, Any]
    previous_reserve_hash: str | None
    reserve_hash: str | None


class ReserveHistoryResponse(BaseModel):
    claim_id: UUID
    currency: str
    current_reserve: Decimal | None
    current_version: int
    current_hash: str | None
    items: list[ReserveHistoryRead]


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_reference: str
    external_reference: str | None
    claim_type: ClaimType
    claim_subtype: ClaimSubtype
    status: ClaimStatus
    priority: ClaimPriority
    incident_date: date
    notification_date: date
    incident_description: str
    estimated_loss: Decimal | None
    current_reserve: Decimal | None
    currency: str
    vessel: VesselBrief
    handler: HandlerBrief | None
    created_at: datetime
    updated_at: datetime


class ClaimListItem(ClaimRead):
    pass


class ClaimListResponse(BaseModel):
    items: list[ClaimListItem]
    total: int
    limit: int
    offset: int


class ClaimFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    field_path: str
    value: Any
    provenance_kind: str
    # Backward-compatible AI provenance. Intake-reviewed facts deliberately leave
    # this null instead of creating a fake AI DocumentExtraction row.
    source_extraction_id: UUID | None
    source_text_extraction_id: UUID | None
    source_document_id: UUID
    source_segment_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime
    version: int


class ClaimFactListResponse(BaseModel):
    items: list[ClaimFactRead]
    total: int
