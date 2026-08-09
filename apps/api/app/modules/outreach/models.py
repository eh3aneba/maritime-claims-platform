from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


ACCOUNT_TYPES = ("marine_insurer", "ship_manager", "p_and_i_correspondent", "average_adjuster", "broker", "other")
STAGES = ("prospect", "contacted", "discovery", "demo", "pilot_qualified", "pilot_proposed", "pilot_active", "paid_pilot", "customer", "no_fit")


class DesignPartnerAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "design_partner_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_design_partner_org_name"),
        CheckConstraint("account_type IN ('marine_insurer','ship_manager','p_and_i_correspondent','average_adjuster','broker','other')", name="ck_design_partner_account_type"),
        CheckConstraint("stage IN ('prospect','contacted','discovery','demo','pilot_qualified','pilot_proposed','pilot_active','paid_pilot','customer','no_fit')", name="ck_design_partner_stage"),
        CheckConstraint("machinery_claim_volume_score BETWEEN 0 AND 5", name="ck_design_partner_volume_score"),
        CheckConstraint("pain_intensity_score BETWEEN 0 AND 5", name="ck_design_partner_pain_score"),
        CheckConstraint("buyer_access_score BETWEEN 0 AND 5", name="ck_design_partner_buyer_score"),
        CheckConstraint("data_availability_score BETWEEN 0 AND 5", name="ck_design_partner_data_score"),
        CheckConstraint("security_fit_score BETWEEN 0 AND 5", name="ck_design_partner_security_score"),
        CheckConstraint("pilot_willingness_score BETWEEN 0 AND 5", name="ck_design_partner_willingness_score"),
        CheckConstraint("qualification_score BETWEEN 0 AND 100", name="ck_design_partner_qualification_score"),
        Index("ix_design_partner_org_score", "organization_id", "qualification_score"),
        Index("ix_design_partner_org_stage", "organization_id", "stage"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="prospect", server_default="prospect")
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    machinery_claim_volume_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pain_intensity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    buyer_access_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    data_availability_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    security_fit_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pilot_willingness_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    qualification_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    qualification_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class DesignPartnerContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "design_partner_contacts"
    __table_args__ = (
        CheckConstraint("role_type IN ('buyer','champion','influencer','security','procurement','user','unknown')", name="ck_design_partner_contact_role"),
        Index("ix_design_partner_contacts_account", "account_id"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("design_partner_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role_type: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutreachTouch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outreach_touches"
    __table_args__ = (
        CheckConstraint("channel IN ('email','linkedin','warm_intro','call','meeting','other')", name="ck_outreach_touch_channel"),
        CheckConstraint("status IN ('planned','sent','replied','no_response','meeting_booked','declined')", name="ck_outreach_touch_status"),
        Index("ix_outreach_touch_account_occurred", "account_id", "occurred_at"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("design_partner_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("design_partner_contacts.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned", server_default="planned")
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class PaidPilotOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paid_pilot_offers"
    __table_args__ = (
        UniqueConstraint("organization_id", "account_id", "version", name="uq_paid_pilot_offer_version"),
        CheckConstraint("status IN ('draft','shared','accepted','rejected','expired')", name="ck_paid_pilot_offer_status"),
        CheckConstraint("fee IS NULL OR fee >= 0", name="ck_paid_pilot_offer_fee_nonnegative"),
        CheckConstraint("duration_days >= 1", name="ck_paid_pilot_offer_duration_positive"),
        Index("ix_paid_pilot_offer_account_status", "account_id", "status"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("design_partner_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    fee: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    deliverables: Mapped[list | None] = mapped_column(JSON, nullable=True)
    customer_responsibilities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    success_criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)
    exclusions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
