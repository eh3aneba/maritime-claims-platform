import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class SettlementStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class SettlementType(str, enum.Enum):
    INTERIM = "interim"
    PARTIAL = "partial"
    FINAL = "final"


class PaymentStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    FIRST_APPROVED = "first_approved"
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    PAID_EXTERNALLY = "paid_externally"
    CANCELLED = "cancelled"


class SettlementProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settlement_proposals"
    __table_args__ = (
        UniqueConstraint("claim_id", "version", name="uq_settlement_claim_version"),
        Index("ix_settlement_org_claim_created", "organization_id", "claim_id", "created_at"),
        CheckConstraint("amount > 0", name="ck_settlement_amount_positive"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    adjustment_statement_id: Mapped[UUID] = mapped_column(ForeignKey("adjustment_statements.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    disposition_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(240))
    settlement_type: Mapped[SettlementType] = mapped_column(Enum(SettlementType, name="settlement_type", native_enum=True, values_callable=enum_values))
    status: Mapped[SettlementStatus] = mapped_column(Enum(SettlementStatus, name="settlement_status", native_enum=True, values_callable=enum_values), default=SettlementStatus.DRAFT, server_default=SettlementStatus.DRAFT.value)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    terms: Mapped[str] = mapped_column(Text)
    release_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    without_prejudice: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_adjustment_hash: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disposition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_authorizations"
    __table_args__ = (
        UniqueConstraint("settlement_id", "sequence", name="uq_payment_settlement_sequence"),
        Index("ix_payment_org_claim_created", "organization_id", "claim_id", "created_at"),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    settlement_id: Mapped[UUID] = mapped_column(ForeignKey("settlement_proposals.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    first_approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    second_approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    paid_recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sequence: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status", native_enum=True, values_callable=enum_values), default=PaymentStatus.DRAFT, server_default=PaymentStatus.DRAFT.value)
    payee: Mapped[str] = mapped_column(String(240))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    purpose: Mapped[str] = mapped_column(Text)
    first_approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    second_approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    second_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_channel: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(240), nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
