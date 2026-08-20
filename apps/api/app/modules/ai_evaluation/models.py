from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIEvaluationSuite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_evaluation_suites"
    __table_args__ = (
        UniqueConstraint("organization_id", "suite_key", name="uq_ai_evaluation_suite_key"),
        UniqueConstraint("activation_request_id", "attempt_number",
                         name="uq_ai_evaluation_suite_attempt"),
        Index("ix_ai_evaluation_suite_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    activation_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_provider_activation_requests.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    suite_key: Mapped[str] = mapped_column(String(120))
    benchmark_profile: Mapped[str] = mapped_column(
        String(80), default="quality_safety_cost_v1", server_default="quality_safety_cost_v1")
    activation_model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    max_input_chars: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    data_mode: Mapped[str] = mapped_column(
        String(40), default="synthetic_deidentified", server_default="synthetic_deidentified")
    min_case_count: Mapped[int] = mapped_column(Integer, default=12, server_default="12")
    min_ce_case_count: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    min_engine_case_count: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    min_precision_bps: Mapped[int] = mapped_column(Integer, default=9000, server_default="9000")
    min_recall_bps: Mapped[int] = mapped_column(Integer, default=8500, server_default="8500")
    max_unsupported_rate_bps: Mapped[int] = mapped_column(Integer, default=200,
                                                          server_default="200")
    min_quote_validity_bps: Mapped[int] = mapped_column(Integer, default=9800,
                                                        server_default="9800")
    max_human_override_bps: Mapped[int] = mapped_column(Integer, default=2000,
                                                        server_default="2000")
    max_p95_latency_ms: Mapped[int] = mapped_column(Integer, default=30000,
                                                    server_default="30000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(Integer, default=500000,
                                                       server_default="500000")
    status: Mapped[str] = mapped_column(String(30), default="collecting",
                                        server_default="collecting")
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evaluation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promotion_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIEvaluationCaseResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_evaluation_case_results"
    __table_args__ = (
        UniqueConstraint("suite_id", "case_key", name="uq_ai_evaluation_case_key"),
        Index("ix_ai_evaluation_case_org_suite", "organization_id", "suite_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    suite_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_evaluation_suites.id", ondelete="CASCADE"), index=True)
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    case_key: Mapped[str] = mapped_column(String(120))
    document_type: Mapped[str] = mapped_column(String(100))
    scenario_type: Mapped[str] = mapped_column(String(40))
    data_mode: Mapped[str] = mapped_column(String(30))
    result: Mapped[str] = mapped_column(String(20))
    field_true_positive: Mapped[int] = mapped_column(Integer)
    field_false_positive: Mapped[int] = mapped_column(Integer)
    field_false_negative: Mapped[int] = mapped_column(Integer)
    extracted_claim_count: Mapped[int] = mapped_column(Integer)
    unsupported_claim_count: Mapped[int] = mapped_column(Integer)
    source_quote_checked_count: Mapped[int] = mapped_column(Integer)
    source_quote_valid_count: Mapped[int] = mapped_column(Integer)
    human_approved_count: Mapped[int] = mapped_column(Integer)
    human_edited_count: Mapped[int] = mapped_column(Integer)
    human_rejected_count: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    observed_provider_cost_microusd: Mapped[int] = mapped_column(Integer)
    boundary_control_passed: Mapped[bool] = mapped_column(default=True, server_default="true")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    result_hash: Mapped[str] = mapped_column(String(64))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIEvaluationReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_evaluation_reviews"
    __table_args__ = (
        UniqueConstraint("suite_id", "review_role", name="uq_ai_evaluation_review_role"),
        Index("ix_ai_evaluation_review_org_suite", "organization_id", "suite_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    suite_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_evaluation_suites.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_role: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
