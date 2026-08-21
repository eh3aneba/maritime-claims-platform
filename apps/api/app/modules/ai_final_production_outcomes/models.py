from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIFinalProductionOutcomeAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_outcome_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "assessment_key", name="uq_ai_fpo_org_key"),
        UniqueConstraint("final_production_authorization_id", "attempt_number", name="uq_ai_fpo_attempt"),
        Index("ix_ai_fpo_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    final_production_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_authorizations.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer)
    assessment_key: Mapped[str] = mapped_column(String(120))
    assessment_profile: Mapped[str] = mapped_column(String(80), default="final_production_outcome_v1", server_default="final_production_outcome_v1")

    final_production_decision_hash: Mapped[str] = mapped_column(String(64))
    final_production_completion_hash: Mapped[str] = mapped_column(String(64))
    final_readiness_assessment_hash: Mapped[str] = mapped_column(String(64))
    final_readiness_decision_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_decision_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_completion_hash: Mapped[str] = mapped_column(String(64))
    broader_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    broader_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    broader_production_decision_hash: Mapped[str] = mapped_column(String(64))
    scale_readiness_assessment_hash: Mapped[str] = mapped_column(String(64))
    scale_readiness_decision_hash: Mapped[str] = mapped_column(String(64))
    scale_up_decision_hash: Mapped[str] = mapped_column(String(64))
    inherited_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    inherited_outcome_decision_hash: Mapped[str] = mapped_column(String(64))

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

    min_reviewed_runs: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    min_runs_per_workflow: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    max_reject_rate_bps: Mapped[int] = mapped_column(Integer, default=400, server_default="400")
    max_edit_rate_bps: Mapped[int] = mapped_column(Integer, default=1800, server_default="1800")
    min_mean_usefulness_bps: Mapped[int] = mapped_column(Integer, default=9200, server_default="9200")
    max_unsupported_output_rate_bps: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    min_source_grounding_validity_bps: Mapped[int] = mapped_column(Integer, default=9980, server_default="9980")
    max_mean_review_seconds: Mapped[int] = mapped_column(Integer, default=240, server_default="240")
    max_p95_latency_ms: Mapped[int] = mapped_column(Integer, default=14000, server_default="14000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(Integer, default=375000, server_default="375000")
    max_quality_regression_bps: Mapped[int] = mapped_column(Integer, default=75, server_default="75")
    max_latency_regression_bps: Mapped[int] = mapped_column(Integer, default=500, server_default="500")
    max_cost_regression_bps: Mapped[int] = mapped_column(Integer, default=500, server_default="500")

    min_business_workflows: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    min_tfta_improvement_bps: Mapped[int] = mapped_column(Integer, default=3000, server_default="3000")
    min_triage_improvement_bps: Mapped[int] = mapped_column(Integer, default=4000, server_default="4000")
    min_handler_effort_improvement_bps: Mapped[int] = mapped_column(Integer, default=2500, server_default="2500")
    min_business_usefulness_bps: Mapped[int] = mapped_column(Integer, default=9200, server_default="9200")

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


class AIFinalProductionOutcomeObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_outcome_observations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "final_production_run_id", name="uq_ai_fpo_obs_run"),
        Index("ix_ai_fpo_obs_org", "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    final_production_run_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_runs.id", ondelete="RESTRICT"), index=True)
    observed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    workflow_type: Mapped[str] = mapped_column(String(100))
    usefulness_rating: Mapped[int] = mapped_column(Integer)
    review_seconds: Mapped[int] = mapped_column(Integer)
    workflow_completed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    observation_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIFinalProductionOutcomeBusinessEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_outcome_business_evidence"
    __table_args__ = (
        UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_fpob_key"),
        Index("ix_ai_fpob_org", "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
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
    handler_usefulness_rating: Mapped[int] = mapped_column(Integer)
    final_claim_decision_human_owned: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIFinalProductionOutcomeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_outcome_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "review_role", name="uq_ai_fpo_review_role"),
        Index("ix_ai_fpo_review_org", "organization_id", "assessment_id", "review_role"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_outcome_assessments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
