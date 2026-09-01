from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ClaimIntelligenceSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_intelligence_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "snapshot_version", name="uq_ci_snapshot_version"),
        UniqueConstraint("organization_id", "claim_id", "source_state_hash", name="uq_ci_source_state"),
        Index("ix_ci_snapshot_claim", "organization_id", "claim_id", "snapshot_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    generated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    snapshot_version: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(40), default="12A.1", server_default="12A.1")
    source_state_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClaimIntelligenceItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_intelligence_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "item_key", name="uq_ci_item_key"),
        Index("ix_ci_item_snapshot", "organization_id", "claim_id", "snapshot_id", "category"),
        Index("ix_ci_item_rank", "snapshot_id", "rank_score"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("claim_intelligence_snapshots.id", ondelete="CASCADE"), index=True)
    item_key: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    urgency_score: Mapped[int] = mapped_column(Integer)
    evidential_value_score: Mapped[int] = mapped_column(Integer)
    rank_score: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text)
    source_refs: Mapped[list] = mapped_column(JSON)
    action_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    related_entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    item_hash: Mapped[str] = mapped_column(String(64))


class ClaimIntelligenceItemDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_intelligence_item_decisions"
    __table_args__ = (
        UniqueConstraint("item_id", "decision_number", name="uq_ci_decision_number"),
        Index("ix_ci_decision_item", "organization_id", "claim_id", "item_id", "decision_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[UUID] = mapped_column(ForeignKey("claim_intelligence_items.id", ondelete="CASCADE"), index=True)
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    converted_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("claim_tasks.id", ondelete="SET NULL"), nullable=True)
    decision_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    edited_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    edited_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
