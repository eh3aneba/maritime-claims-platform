from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RecoveryTimebarSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "recovery_timebar_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "snapshot_version", name="uq_recovery_timebar_snapshot_version"),
        UniqueConstraint("organization_id", "claim_id", "source_state_hash", name="uq_recovery_timebar_source_state"),
        Index("ix_recovery_timebar_snapshot_claim", "organization_id", "claim_id", "snapshot_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    generated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(30), nullable=False)
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecoveryTimebarEvaluation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "recovery_timebar_evaluations"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "evaluation_key", name="uq_recovery_timebar_eval_key"),
        Index("ix_recovery_timebar_eval_claim", "organization_id", "claim_id", "kind", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("recovery_timebar_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)

    evaluation_key: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    counterparty: Mapped[str | None] = mapped_column(String(240), nullable=True)
    candidate_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    candidate_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_implication: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    missing_prerequisites: Mapped[list] = mapped_column(JSON, nullable=False)
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    evaluation_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RecoveryTimebarDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recovery_timebar_decisions"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "decision_number", name="uq_recovery_timebar_decision_number"),
        Index("ix_recovery_timebar_decision_eval", "organization_id", "claim_id", "evaluation_id", "decision_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("recovery_timebar_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("recovery_timebar_evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    converted_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("claim_tasks.id", ondelete="SET NULL"), nullable=True)

    evaluation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    edited_candidate_implication: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecoveryCounterparty(UUIDPrimaryKeyMixin, Base):
    """Append-only human allegation/role context for a potential recovery counterparty."""

    __tablename__ = "recovery_counterparties"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "claim_id", "counterparty_key", "version",
            name="uq_recovery_counterparty_version",
        ),
        Index("ix_recovery_counterparty_claim", "organization_id", "claim_id", "counterparty_key", "version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    counterparty_key: Mapped[UUID] = mapped_column(nullable=False, default=uuid4, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("recovery_counterparties.id", ondelete="RESTRICT"), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(240), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    allegation_basis: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True)
    source_document_family_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TimebarScenario(UUIDPrimaryKeyMixin, Base):
    """Immutable version of a human-defined alternative limitation/time-bar scenario."""

    __tablename__ = "timebar_scenarios"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "claim_id", "scenario_key", "version",
            name="uq_timebar_scenario_version",
        ),
        Index("ix_timebar_scenario_claim", "organization_id", "claim_id", "scenario_key", "version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_key: Mapped[UUID] = mapped_column(nullable=False, default=uuid4, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("timebar_scenarios.id", ondelete="RESTRICT"), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    counterparty_id: Mapped[UUID | None] = mapped_column(ForeignKey("recovery_counterparties.id", ondelete="RESTRICT"), nullable=True)

    title: Mapped[str] = mapped_column(String(220), nullable=False)
    legal_basis: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True)
    source_document_family_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_value: Mapped[int] = mapped_column(Integer, nullable=False)
    period_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    extension_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extension_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    extension_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_deadline: Mapped[date] = mapped_column(Date, nullable=False)
    scenario_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TimebarScenarioReview(UUIDPrimaryKeyMixin, Base):
    """Append-only human review lineage, separate from computed candidate dates."""

    __tablename__ = "timebar_scenario_reviews"
    __table_args__ = (
        UniqueConstraint("scenario_id", "review_number", name="uq_timebar_scenario_review_number"),
        Index("ix_timebar_scenario_review", "organization_id", "claim_id", "scenario_id", "review_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id: Mapped[UUID] = mapped_column(ForeignKey("timebar_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    scenario_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    confirmed_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_review_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
