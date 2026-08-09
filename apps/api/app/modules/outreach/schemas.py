from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["marine_insurer","ship_manager","p_and_i_correspondent","average_adjuster","broker","other"]
AccountStage = Literal["prospect","contacted","discovery","demo","pilot_qualified","pilot_proposed","pilot_active","paid_pilot","customer","no_fit"]


class DesignPartnerAccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    account_type: AccountType
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    machinery_claim_volume_score: int = Field(default=0, ge=0, le=5)
    pain_intensity_score: int = Field(default=0, ge=0, le=5)
    buyer_access_score: int = Field(default=0, ge=0, le=5)
    data_availability_score: int = Field(default=0, ge=0, le=5)
    security_fit_score: int = Field(default=0, ge=0, le=5)
    pilot_willingness_score: int = Field(default=0, ge=0, le=5)


class DesignPartnerAccountUpdate(BaseModel):
    stage: AccountStage | None = None
    notes: str | None = Field(default=None, max_length=5000)
    next_step: str | None = Field(default=None, max_length=2000)
    next_step_due_date: date | None = None
    machinery_claim_volume_score: int | None = Field(default=None, ge=0, le=5)
    pain_intensity_score: int | None = Field(default=None, ge=0, le=5)
    buyer_access_score: int | None = Field(default=None, ge=0, le=5)
    data_availability_score: int | None = Field(default=None, ge=0, le=5)
    security_fit_score: int | None = Field(default=None, ge=0, le=5)
    pilot_willingness_score: int | None = Field(default=None, ge=0, le=5)


class DesignPartnerAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    account_type: str
    country: str | None
    region: str | None
    stage: str
    qualification_score: int
    qualification_rationale: str | None
    next_step: str | None
    next_step_due_date: date | None
    machinery_claim_volume_score: int
    pain_intensity_score: int
    buyer_access_score: int
    data_availability_score: int
    security_fit_score: int
    pilot_willingness_score: int
    created_at: datetime


class CohortAccountRead(DesignPartnerAccountRead):
    qualification_band: str
    recommended_action: str


class CohortSummary(BaseModel):
    target_qualified_partners: int = 3
    target_paid_pilots: int = 1
    accounts_total: int
    a_tier: int
    b_tier: int
    pilot_qualified: int
    paid_pilots: int
    target_progress: dict[str, int]
    accounts: list[CohortAccountRead]


class DesignPartnerContactCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    linkedin_url: str | None = Field(default=None, max_length=500)
    role_type: Literal["buyer","champion","influencer","security","procurement","user","unknown"] = "unknown"
    notes: str | None = Field(default=None, max_length=2000)


class DesignPartnerContactRead(DesignPartnerContactCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    created_at: datetime


class OutreachTouchCreate(BaseModel):
    contact_id: UUID | None = None
    channel: Literal["email","linkedin","warm_intro","call","meeting","other"]
    status: Literal["planned","sent","replied","no_response","meeting_booked","declined"] = "planned"
    subject: str | None = Field(default=None, max_length=500)
    message_summary: str | None = Field(default=None, max_length=5000)
    next_step: str | None = Field(default=None, max_length=2000)
    next_step_due_date: date | None = None


class OutreachTouchRead(OutreachTouchCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    created_by_id: UUID | None
    occurred_at: datetime


class PaidPilotOfferCreate(BaseModel):
    duration_days: int = Field(default=30, ge=1, le=365)
    fee: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    scope: str = Field(min_length=10, max_length=10000)
    deliverables: list[str] = Field(default_factory=list)
    customer_responsibilities: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5000)


class PaidPilotOfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    version: int
    status: str
    duration_days: int
    fee: Decimal | None
    currency: str
    scope: str
    deliverables: list | None
    customer_responsibilities: list | None
    success_criteria: list | None
    exclusions: list | None
    notes: str | None
    created_at: datetime
