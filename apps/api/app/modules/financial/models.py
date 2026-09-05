from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class CostReviewStatus(str, enum.Enum):
    CLAIMED = "claimed"
    UNDER_REVIEW = "under_review"
    POTENTIALLY_RECOVERABLE = "potentially_recoverable"
    POTENTIALLY_NON_RECOVERABLE = "potentially_non_recoverable"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PAID = "paid"


class FinancialFlagType(str, enum.Enum):
    POSSIBLE_DUPLICATE = "possible_duplicate"
    INVOICE_PREDATES_INCIDENT = "invoice_predates_incident"
    POTENTIAL_BETTERMENT = "potential_betterment"
    POTENTIAL_ORDINARY_MAINTENANCE = "potential_ordinary_maintenance"
    QUOTE_SCOPE_DIFFERENCE = "quote_scope_difference"
    TOTAL_MISMATCH = "total_mismatch"


class FinancialFlagStatus(str, enum.Enum):
    OPEN = "open"
    EXPLAINED = "explained"
    RESOLVED = "resolved"
    IRRELEVANT = "irrelevant"


class CostItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current derived financial evidence row.

    CostItem is intentionally not the human-review authority. It is rebuilt from
    current usable reviewed source evidence. Human dispositions are preserved in
    CostReviewDecision so source evolution cannot silently transfer or erase them.
    """

    __tablename__ = "cost_items"
    __table_args__ = (
        Index("ix_cost_items_org_claim", "organization_id", "claim_id"),
        CheckConstraint("amount >= 0", name="ck_cost_items_amount_nonnegative"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ai_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    line_index: Mapped[int] = mapped_column(nullable=False)
    document_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(255))
    document_number: Mapped[str | None] = mapped_column(String(120))
    document_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    review_status: Mapped[CostReviewStatus] = mapped_column(
        Enum(
            CostReviewStatus,
            name="cost_review_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=CostReviewStatus.UNDER_REVIEW,
        server_default=CostReviewStatus.UNDER_REVIEW.value,
    )
    source_field_prefix: Mapped[str] = mapped_column(String(220), nullable=False)


class CostReviewDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only human disposition on one exact financial evidence state.

    The disposition is operational cost-review state only. It does not determine
    coverage, recoverability, admissibility, betterment/depreciation, reserve,
    settlement, payment or any legal outcome.
    """

    __tablename__ = "cost_review_decisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "item_key",
            "decision_number",
            name="uq_cost_review_decision_number",
        ),
        Index(
            "ix_cost_review_decisions_org_claim_item",
            "organization_id",
            "claim_id",
            "item_key",
            "decision_number",
        ),
        CheckConstraint("state_version >= 1", name="ck_cost_review_decision_state_version"),
        CheckConstraint("decision_number >= 1", name="ck_cost_review_decision_number"),
        CheckConstraint(
            "status IN ('claimed','under_review','potentially_recoverable','potentially_non_recoverable','accepted','rejected','paid')",
            name="ck_cost_review_decision_status",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    item_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    item_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class FinancialFlag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_flags"
    __table_args__ = (
        Index("ix_financial_flags_org_claim", "organization_id", "claim_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    flag_type: Mapped[FinancialFlagType] = mapped_column(
        Enum(
            FinancialFlagType,
            name="financial_flag_type",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    fingerprint: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[FinancialFlagStatus] = mapped_column(
        Enum(
            FinancialFlagStatus,
            name="financial_flag_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=FinancialFlagStatus.OPEN,
        server_default=FinancialFlagStatus.OPEN.value,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReserveHistory(UUIDPrimaryKeyMixin, Base):
    """Append-only authoritative reserve history.

    New lineage-bound rows are versioned, idempotent and hash-chained. Historical
    rows that predate Phase 13.6C deliberately retain NULL lineage fields and the
    `legacy_unbound` source kind instead of fabricated provenance.
    """

    __tablename__ = "reserve_history"
    __table_args__ = (
        Index("ix_reserve_history_org_claim_created", "organization_id", "claim_id", "created_at"),
        Index("ix_reserve_history_org_claim_sequence", "organization_id", "claim_id", "sequence"),
        Index("ix_reserve_history_reserve_hash", "reserve_hash"),
        UniqueConstraint("organization_id", "claim_id", "sequence", name="uq_reserve_history_claim_sequence"),
        UniqueConstraint("organization_id", "claim_id", "idempotency_key", name="uq_reserve_history_claim_idempotency"),
        CheckConstraint("amount >= 0", name="ck_reserve_history_amount_nonnegative"),
        CheckConstraint("sequence IS NULL OR sequence >= 1", name="ck_reserve_history_sequence_positive"),
        CheckConstraint(
            "source_kind IN ('legacy_unbound','manual','reserve_support','adjustment')",
            name="ck_reserve_history_source_kind",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy_unbound", server_default="legacy_unbound")
    source_reference_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_reserve_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserve_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
