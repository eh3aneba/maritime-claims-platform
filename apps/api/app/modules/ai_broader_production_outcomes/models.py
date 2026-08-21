from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIBroaderProductionOutcomeAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_outcome_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "assessment_key", name="uq_ai_bpo_org_key"),
        UniqueConstraint("broader_production_authorization_id", "attempt_number", name="uq_ai_bpo_attempt"),
        Index("ix_ai_bpo_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    broader_production_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_authorizations.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer)
    assessment_key: Mapped[str] = mapped_column(String(120))
    assessment_profile: Mapped[str] = mapped_column(String(80), default="broader_production_readiness_v1", server_default="broader_production_readiness_v1")

    broader_production_decision_hash: Mapped[str] = mapped_column(String(64))
    readiness_assessment_hash: Mapped[str] = mapped_column(String(64))
    readiness_decision_hash: Mapped[str] = mapped_column(String(64))
    scale_up_decision_hash: Mapped[str] = mapped_column(String(64))
    inherited_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    inherited_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    rollout_percentage: Mapped[int] = mapped_column(Integer)

    min_reviewed_runs: Mapped[int] = mapped_column(Integer, default=40, server_default="40")
    min_runs_per_workflow: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    max_reject_rate_bps: Mapped[int] = mapped_column(Integer, default=600, server_default="600")
    max_edit_rate_bps: Mapped[int] = mapped_column(Integer, default=2500, server_default="2500")
    min_mean_usefulness_bps: Mapped[int] = mapped_column(Integer, default=8800, server_default="8800")
    max_unsupported_output_rate_bps: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    min_source_grounding_validity_bps: Mapped[int] = mapped_column(Integer, default=9950, server_default="9950")
    max_mean_review_seconds: Mapped[int] = mapped_column(Integer, default=360, server_default="360")
    max_p95_latency_ms: Mapped[int] = mapped_column(Integer, default=18000, server_default="18000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(Integer, default=450000, server_default="450000")
    max_quality_regression_bps: Mapped[int] = mapped_column(Integer, default=200, server_default="200")
    max_latency_regression_bps: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    max_cost_regression_bps: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")

    status: Mapped[str] = mapped_column(String(30), default="collecting", server_default="collecting")
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assessment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIBroaderProductionOutcomeObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_outcome_observations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "broader_production_run_id", name="uq_ai_bpo_obs_run"),
        Index("ix_ai_bpo_obs_org", "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    broader_production_run_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_runs.id", ondelete="RESTRICT"), index=True)
    observed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    workflow_type: Mapped[str] = mapped_column(String(100))
    usefulness_rating: Mapped[int] = mapped_column(Integer)
    review_seconds: Mapped[int] = mapped_column(Integer)
    workflow_completed: Mapped[bool] = mapped_column(default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    observation_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIBroaderProductionOutcomeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_outcome_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "review_role", name="uq_ai_bpo_review_role"),
        Index("ix_ai_bpo_review_org", "organization_id", "assessment_id", "review_role"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
