import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class AdjustmentStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AdjustmentTreatment(str, enum.Enum):
    PENDING = "pending"
    INCLUDED = "included"
    EXCLUDED = "excluded"
    APPORTIONED = "apportioned"
    CREDIT = "credit"


class AdjustmentBasis(str, enum.Enum):
    UNALLOCATED = "unallocated"
    PARTICULAR_AVERAGE = "particular_average"
    GENERAL_AVERAGE = "general_average"
    SUE_AND_LABOUR = "sue_and_labour"
    RDC = "rdc"
    OTHER = "other"
    NOT_APPLICABLE = "not_applicable"


class AdjustmentStatement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "adjustment_statements"
    __table_args__ = (
        UniqueConstraint("claim_id", "version", name="uq_adjustment_statement_claim_version"),
        Index("ix_adjustment_statements_org_claim_created", "organization_id", "claim_id", "created_at"),
        CheckConstraint("deductible_amount >= 0", name="ck_adjustment_deductible_nonnegative"),
        CheckConstraint("other_deduction_amount >= 0", name="ck_adjustment_other_deduction_nonnegative"),
        CheckConstraint("source_manifest_version >= 1", name="ck_adjustment_source_manifest_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rebased_from_statement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("adjustment_statements.id", ondelete="SET NULL"), nullable=True, index=True
    )

    version: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[AdjustmentStatus] = mapped_column(Enum(AdjustmentStatus, name="adjustment_status", native_enum=True, values_callable=enum_values), nullable=False, default=AdjustmentStatus.DRAFT, server_default=AdjustmentStatus.DRAFT.value)

    deductible_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    deductible_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    other_deduction_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    other_deduction_basis: Mapped[str | None] = mapped_column(Text, nullable=True)

    gross_claimed: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    gross_considered: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    net_adjusted: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")

    source_manifest: Mapped[list] = mapped_column(JSON, nullable=False)
    source_manifest_version: Mapped[int] = mapped_column(nullable=False, default=2, server_default="1")
    source_state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdjustmentLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "adjustment_lines"
    __table_args__ = (
        Index("ix_adjustment_lines_statement_order", "statement_id", "sort_order"),
        Index("ix_adjustment_lines_org_claim", "organization_id", "claim_id"),
        CheckConstraint("claimed_amount >= 0", name="ck_adjustment_line_claimed_nonnegative"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    statement_id: Mapped[UUID] = mapped_column(ForeignKey("adjustment_statements.id", ondelete="CASCADE"), nullable=False, index=True)
    cost_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("cost_items.id", ondelete="SET NULL"), nullable=True, index=True)
    source_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)

    sort_order: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    considered_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    treatment: Mapped[AdjustmentTreatment] = mapped_column(Enum(AdjustmentTreatment, name="adjustment_treatment", native_enum=True, values_callable=enum_values), nullable=False, default=AdjustmentTreatment.PENDING, server_default=AdjustmentTreatment.PENDING.value)
    basis: Mapped[AdjustmentBasis] = mapped_column(Enum(AdjustmentBasis, name="adjustment_basis", native_enum=True, values_callable=enum_values), nullable=False, default=AdjustmentBasis.UNALLOCATED, server_default=AdjustmentBasis.UNALLOCATED.value)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    financial_controls: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
