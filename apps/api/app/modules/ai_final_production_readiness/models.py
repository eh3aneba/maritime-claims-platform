from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIFinalProductionReadinessAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_readiness_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "assessment_key", name="uq_ai_fpra_org_key"),
        UniqueConstraint("high_coverage_outcome_assessment_id", "attempt_number", name="uq_ai_fpra_attempt"),
        Index("ix_ai_fpra_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    high_coverage_outcome_assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_high_coverage_outcome_assessments.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer)
    assessment_key: Mapped[str] = mapped_column(String(120))
    assessment_profile: Mapped[str] = mapped_column(String(80), default="final_production_ai_readiness_v1", server_default="final_production_ai_readiness_v1")

    high_coverage_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_decision_hash: Mapped[str] = mapped_column(String(64))
    high_coverage_completion_hash: Mapped[str] = mapped_column(String(64))
    broader_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    broader_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
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

    min_claim_workflows: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    min_tfta_improvement_bps: Mapped[int] = mapped_column(Integer, default=3000, server_default="3000")
    min_triage_improvement_bps: Mapped[int] = mapped_column(Integer, default=4000, server_default="4000")
    min_handler_effort_improvement_bps: Mapped[int] = mapped_column(Integer, default=2500, server_default="2500")
    min_handler_usefulness_bps: Mapped[int] = mapped_column(Integer, default=9000, server_default="9000")

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


class AIFinalProductionReadinessClaimEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_readiness_claim_evidence"
    __table_args__ = (
        UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_fprc_key"),
        Index("ix_ai_fprc_org", "organization_id", "assessment_id", "workflow_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_readiness_assessments.id", ondelete="CASCADE"), index=True)
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
    final_claim_decision_human_owned: Mapped[bool] = mapped_column(default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIFinalProductionReadinessControlEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_readiness_control_evidence"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_key", name="uq_ai_fprx_control"),
        Index("ix_ai_fprx_org", "organization_id", "assessment_id", "control_key"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_readiness_assessments.id", ondelete="CASCADE"), index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    control_key: Mapped[str] = mapped_column(String(80))
    passed: Mapped[bool] = mapped_column(default=False, server_default="false")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIFinalProductionReadinessReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_final_production_readiness_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "review_role", name="uq_ai_fprr_role"),
        Index("ix_ai_fprr_org", "organization_id", "assessment_id", "review_role"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_final_production_readiness_assessments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
