from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIBoundedFullProductionOutcomeAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_bounded_full_production_outcome_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "assessment_key", name="uq_ai_bfpo_org_key"),
        UniqueConstraint("bounded_full_authorization_id", "attempt_number", name="uq_ai_bfpo_attempt"),
        Index("ix_ai_bfpo_org_status", "organization_id", "status", "created_at"),
        Index("ix_ai_bfpo_auth", "bounded_full_authorization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    bounded_full_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_authorizations.id", ondelete="RESTRICT"))
    near_universal_outcome_assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_near_universal_outcome_assessments.id", ondelete="RESTRICT"))
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer)
    assessment_key: Mapped[str] = mapped_column(String(120))
    assessment_profile: Mapped[str] = mapped_column(String(80), default="bounded_full_outcome_v1", server_default="bounded_full_outcome_v1")

    bounded_full_decision_hash: Mapped[str] = mapped_column(String(64))
    bounded_full_completion_hash: Mapped[str] = mapped_column(String(64))
    near_universal_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    near_universal_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    near_universal_decision_hash: Mapped[str] = mapped_column(String(64))
    near_universal_completion_hash: Mapped[str] = mapped_column(String(64))

    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    max_input_chars: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    allowed_document_types: Mapped[list] = mapped_column(JSON)
    rollout_percentage: Mapped[int] = mapped_column(Integer)
    max_claims: Mapped[int] = mapped_column(Integer)
    max_documents: Mapped[int] = mapped_column(Integer)
    max_users: Mapped[int] = mapped_column(Integer)
    max_provider_runs: Mapped[int] = mapped_column(Integer)

    min_reviewed_runs: Mapped[int] = mapped_column(Integer, default=200, server_default="200")
    min_runs_per_workflow: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    max_reject_rate_bps: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    max_edit_rate_bps: Mapped[int] = mapped_column(Integer, default=1500, server_default="1500")
    min_mean_usefulness_bps: Mapped[int] = mapped_column(Integer, default=9500, server_default="9500")
    max_unsupported_output_rate_bps: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    min_source_grounding_validity_bps: Mapped[int] = mapped_column(Integer, default=9990, server_default="9990")
    max_mean_review_seconds: Mapped[int] = mapped_column(Integer, default=195, server_default="195")
    max_p95_latency_ms: Mapped[int] = mapped_column(Integer, default=12000, server_default="12000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(Integer, default=325000, server_default="325000")
    max_quality_regression_bps: Mapped[int] = mapped_column(Integer, default=40, server_default="40")
    max_latency_regression_bps: Mapped[int] = mapped_column(Integer, default=350, server_default="350")
    max_cost_regression_bps: Mapped[int] = mapped_column(Integer, default=350, server_default="350")

    min_business_workflows: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    min_tfta_improvement_bps: Mapped[int] = mapped_column(Integer, default=3500, server_default="3500")
    min_triage_improvement_bps: Mapped[int] = mapped_column(Integer, default=4500, server_default="4500")
    min_handler_effort_improvement_bps: Mapped[int] = mapped_column(Integer, default=3000, server_default="3000")
    min_business_usefulness_bps: Mapped[int] = mapped_column(Integer, default=9500, server_default="9500")
    min_enterprise_controls: Mapped[int] = mapped_column(Integer, default=10, server_default="10")

    status: Mapped[str] = mapped_column(String(30), default="collecting", server_default="collecting")
    outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assessment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIBoundedFullProductionOutcomeObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_bounded_full_production_outcome_observations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "bounded_full_run_id", name="uq_ai_bfpo_obs_run"),
        Index("ix_ai_bfpo_obs_org", "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    bounded_full_run_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_runs.id", ondelete="RESTRICT"), index=True)
    observed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    workflow_type: Mapped[str] = mapped_column(String(100))
    usefulness_rating: Mapped[int] = mapped_column(Integer)
    review_seconds: Mapped[int] = mapped_column(Integer)
    workflow_completed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    observation_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIBoundedFullProductionOutcomeBusinessEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_bounded_full_production_outcome_business_evidence"
    __table_args__ = (
        UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_bfpob_key"),
        Index("ix_ai_bfpob_org", "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evidence_key: Mapped[str] = mapped_column(String(120))
    workflow_type: Mapped[str] = mapped_column(String(100))
    baseline_tfta_seconds: Mapped[int] = mapped_column(Integer)
    assisted_tfta_seconds: Mapped[int] = mapped_column(Integer)
    baseline_triage_seconds: Mapped[int] = mapped_column(Integer)
    assisted_triage_seconds: Mapped[int] = mapped_column(Integer)
    baseline_handler_effort_seconds: Mapped[int] = mapped_column(Integer)
    assisted_handler_effort_seconds: Mapped[int] = mapped_column(Integer)
    baseline_rework_count: Mapped[int] = mapped_column(Integer)
    assisted_rework_count: Mapped[int] = mapped_column(Integer)
    baseline_escalation_count: Mapped[int] = mapped_column(Integer)
    assisted_escalation_count: Mapped[int] = mapped_column(Integer)
    baseline_correction_count: Mapped[int] = mapped_column(Integer)
    assisted_correction_count: Mapped[int] = mapped_column(Integer)
    handler_usefulness_rating: Mapped[int] = mapped_column(Integer)
    final_claim_decision_human_owned: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIBoundedFullProductionOutcomeEnterpriseEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_bounded_full_production_outcome_enterprise_evidence"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_category", name="uq_ai_bfpoe_category"),
        Index("ix_ai_bfpoe_org", "organization_id", "assessment_id", "control_category"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    control_category: Mapped[str] = mapped_column(String(80))
    evidence_key: Mapped[str] = mapped_column(String(120))
    passed: Mapped[bool] = mapped_column(Boolean)
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIBoundedFullProductionOutcomeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_bounded_full_production_outcome_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "review_role", name="uq_ai_bfpo_review_role"),
        Index("ix_ai_bfpo_review_org", "organization_id", "assessment_id", "review_role"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
