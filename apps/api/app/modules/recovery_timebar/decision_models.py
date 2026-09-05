from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class RecoveryPursuitDecision(UUIDPrimaryKeyMixin, Base):
    """Immutable human recovery disposition version for one logical counterparty path."""

    __tablename__ = "recovery_pursuit_decisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "claim_id", "decision_key", "version",
            name="uq_recovery_pursuit_decision_version",
        ),
        Index(
            "ix_recovery_pursuit_decision_claim",
            "organization_id", "claim_id", "decision_key", "version",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_key: Mapped[UUID] = mapped_column(nullable=False, default=uuid4, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recovery_pursuit_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    counterparty_id: Mapped[UUID] = mapped_column(
        ForeignKey("recovery_counterparties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    basis_reference: Mapped[str] = mapped_column(Text, nullable=False)
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecoveryActionLog(UUIDPrimaryKeyMixin, Base):
    """Append-only human recovery action/correspondence record with hash chaining."""

    __tablename__ = "recovery_action_logs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "claim_id", "decision_key", "action_number",
            name="uq_recovery_action_number",
        ),
        Index(
            "ix_recovery_action_claim",
            "organization_id", "claim_id", "decision_key", "action_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_key: Mapped[UUID] = mapped_column(nullable=False, index=True)
    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("recovery_pursuit_decisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    external_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_response_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_action_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
