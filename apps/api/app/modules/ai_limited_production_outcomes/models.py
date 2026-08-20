from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AILimitedProductionOutcomeAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_limited_production_outcome_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "assessment_key",
                         name="uq_ai_limited_outcome_org_key"),
        UniqueConstraint("authorization_id", "attempt_number",
                         name="uq_ai_limited_outcome_attempt"),
        Index("ix_ai_limited_outcome_org_status",
              "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_limited_production_authorizations.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer)
    assessment_key: Mapped[str] = mapped_column(String(120))
    assessment_profile: Mapped[str] = mapped_column(
        String(80), default="limited_production_graduation_v1",
        server_default="limited_production_graduation_v1")

    authorization_decision_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    rollout_percentage: Mapped[int] = mapped_column(Integer)

    max_reject_rate_bps: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    max_edit_rate_bps: Mapped[int] = mapped_column(Integer, default=3500, server_default="3500")
    min_mean_usefulness_bps: Mapped[int] = mapped_column(
        Integer, default=8400, server_default="8400")
    max_unsupported_output_rate_bps: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100")
    min_source_grounding_validity_bps: Mapped[int] = mapped_column(
        Integer, default=9900, server_default="9900")
    max_mean_review_seconds: Mapped[int] = mapped_column(
        Integer, default=480, server_default="480")
    max_p95_latency_ms: Mapped[int] = mapped_column(
        Integer, default=20000, server_default="20000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(
        Integer, default=500000, server_default="500000")
    max_quality_regression_bps: Mapped[int] = mapped_column(
        Integer, default=500, server_default="500")
    max_latency_regression_bps: Mapped[int] = mapped_column(
        Integer, default=2000, server_default="2000")
    max_cost_regression_bps: Mapped[int] = mapped_column(
        Integer, default=2000, server_default="2000")

    status: Mapped[str] = mapped_column(
        String(30), default="collecting", server_default="collecting")
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assessment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AILimitedProductionOutcomeObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_limited_production_outcome_observations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "limited_run_id",
                         name="uq_ai_limited_outcome_observation_run"),
        Index("ix_ai_limited_outcome_observation_org",
              "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_limited_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    limited_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_limited_production_runs.id", ondelete="RESTRICT"), index=True)
    observed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    workflow_type: Mapped[str] = mapped_column(String(100))
    usefulness_rating: Mapped[int] = mapped_column(Integer)
    review_seconds: Mapped[int] = mapped_column(Integer)
    unsupported_output_count: Mapped[int] = mapped_column(Integer)
    source_grounded_output_count: Mapped[int] = mapped_column(Integer)
    source_grounding_total_count: Mapped[int] = mapped_column(Integer)
    workflow_completed: Mapped[bool] = mapped_column(default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    observation_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AILimitedProductionOutcomeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_limited_production_outcome_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "review_role",
                         name="uq_ai_limited_outcome_review_role"),
        Index("ix_ai_limited_outcome_review_org",
              "organization_id", "assessment_id", "review_role"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_limited_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
