from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SeverityReserveSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "severity_reserve_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "snapshot_version", name="uq_severity_reserve_snapshot_version"),
        UniqueConstraint("organization_id", "claim_id", "source_state_hash", name="uq_severity_reserve_source_state"),
        Index("ix_severity_reserve_snapshot_claim", "organization_id", "claim_id", "snapshot_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    generated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(30), nullable=False)
    source_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SeverityReserveEvaluation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "severity_reserve_evaluations"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "evaluation_key", name="uq_severity_reserve_eval_key"),
        Index("ix_severity_reserve_eval_claim", "organization_id", "claim_id", "kind", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("severity_reserve_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)

    evaluation_key: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    severity_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    severity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    lower_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    upper_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_implication: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    factors: Mapped[list] = mapped_column(JSON, nullable=False)
    missing_prerequisites: Mapped[list] = mapped_column(JSON, nullable=False)
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    evaluation_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SeverityReserveDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "severity_reserve_decisions"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "decision_number", name="uq_severity_reserve_decision_number"),
        Index("ix_severity_reserve_decision_eval", "organization_id", "claim_id", "evaluation_id", "decision_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("severity_reserve_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("severity_reserve_evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    evaluation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    edited_severity_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    edited_lower_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    edited_upper_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
