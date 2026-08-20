from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIPilotOutcomeAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_pilot_outcome_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "assessment_key",
                         name="uq_ai_pilot_outcome_org_key"),
        UniqueConstraint("pilot_id", "attempt_number",
                         name="uq_ai_pilot_outcome_attempt"),
        Index("ix_ai_pilot_outcome_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    pilot_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_private_pilot_authorizations.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    assessment_key: Mapped[str] = mapped_column(String(120))
    assessment_profile: Mapped[str] = mapped_column(
        String(60), default="private_pilot_exit_v1", server_default="private_pilot_exit_v1")
    min_run_count: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    min_ce_run_count: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    min_engine_run_count: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    max_reject_rate_bps: Mapped[int] = mapped_column(Integer, default=2000, server_default="2000")
    max_edit_rate_bps: Mapped[int] = mapped_column(Integer, default=5000, server_default="5000")
    min_mean_usefulness_bps: Mapped[int] = mapped_column(
        Integer, default=8000, server_default="8000")
    max_mean_review_seconds: Mapped[int] = mapped_column(
        Integer, default=600, server_default="600")
    max_p95_latency_ms: Mapped[int] = mapped_column(
        Integer, default=30000, server_default="30000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(
        Integer, default=500000, server_default="500000")
    status: Mapped[str] = mapped_column(
        String(30), default="collecting", server_default="collecting")
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assessment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIPilotWorkflowObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_pilot_workflow_observations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "pilot_run_id",
                         name="uq_ai_pilot_observation_run"),
        Index("ix_ai_pilot_observation_org_assessment",
              "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_pilot_outcome_assessments.id", ondelete="CASCADE"), index=True)
    pilot_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_private_pilot_runs.id", ondelete="RESTRICT"), index=True)
    observed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    workflow_type: Mapped[str] = mapped_column(String(100))
    usefulness_rating: Mapped[int] = mapped_column(Integer)
    review_seconds: Mapped[int] = mapped_column(Integer)
    workflow_completed: Mapped[bool] = mapped_column(default=True, server_default="true")
    boundary_control_passed: Mapped[bool] = mapped_column(default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    observation_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIPilotOutcomeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_pilot_outcome_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "review_role",
                         name="uq_ai_pilot_outcome_review_role"),
        Index("ix_ai_pilot_outcome_review_org",
              "organization_id", "assessment_id", "review_role"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_pilot_outcome_assessments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
