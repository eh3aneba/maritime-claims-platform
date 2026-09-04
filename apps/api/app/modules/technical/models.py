from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


TECHNICAL_DECISION_ACTIONS = (
    "keep_open",
    "supported_for_investigation",
    "not_supported",
    "needs_more_evidence",
)


class TechnicalInvestigationDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only human disposition on one evidence-grounded technical topic.

    The current topic state remains computed from reviewed evidence. This table stores
    only what a human decided about the exact evidence state they saw; it is not an
    authoritative causation, coverage or liability determination.
    """

    __tablename__ = "technical_investigation_decisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "topic_key",
            "decision_number",
            name="uq_technical_investigation_decision_number",
        ),
        Index(
            "ix_technical_investigation_decisions_org_claim_topic",
            "organization_id",
            "claim_id",
            "topic_key",
            "decision_number",
        ),
        CheckConstraint("state_version >= 1", name="ck_technical_investigation_decision_state_version"),
        CheckConstraint("decision_number >= 1", name="ck_technical_investigation_decision_number"),
        CheckConstraint(
            "action IN ('keep_open','supported_for_investigation','not_supported','needs_more_evidence')",
            name="ck_technical_investigation_decision_action",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    topic_key: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    topic_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
