from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PilotSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pilot_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','completed','abandoned')", name="ck_pilot_sessions_status"),
        CheckConstraint("baseline_assessment_minutes IS NULL OR baseline_assessment_minutes >= 0", name="ck_pilot_sessions_baseline_nonnegative"),
        Index("ix_pilot_sessions_org_started", "organization_id", "started_at"),
        Index("ix_pilot_sessions_claim_status", "claim_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    participant_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    facilitator_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    participant_role: Mapped[str] = mapped_column(String(100), nullable=False, default="claims_handler", server_default="claims_handler")
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_assessment_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PilotEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only telemetry. Server actions should be preferred over browser-only events."""

    __tablename__ = "pilot_events"
    __table_args__ = (
        CheckConstraint("source IN ('server','browser')", name="ck_pilot_events_source"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_pilot_events_duration_nonnegative"),
        Index("ix_pilot_events_session_created", "session_id", "created_at"),
        Index("ix_pilot_events_org_type", "organization_id", "event_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("pilot_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="server", server_default="server")
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PilotFeedback(UUIDPrimaryKeyMixin, Base):
    """Append-only design-partner feedback and validation judgments."""

    __tablename__ = "pilot_feedback"
    __table_args__ = (
        CheckConstraint("category IN ('usability','ai_quality','rules','workflow','feature_gap','value','missing_document','technical','financial')", name="ck_pilot_feedback_category"),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_pilot_feedback_severity"),
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_pilot_feedback_rating"),
        Index("ix_pilot_feedback_session_created", "session_id", "created_at"),
        Index("ix_pilot_feedback_org_category", "organization_id", "category"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("pilot_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium", server_default="medium")
    verdict: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PilotCommercialValidation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Commercial discovery captured for one design-partner pilot session.

    These records are product-validation data only. They must never alter claim
    coverage, causation, reserve, settlement, or evidentiary records.
    """

    __tablename__ = "pilot_commercial_validations"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_pilot_commercial_validation_session"),
        CheckConstraint("annual_claim_volume IS NULL OR annual_claim_volume >= 0", name="ck_pilot_commercial_annual_claim_volume_nonnegative"),
        CheckConstraint("expected_users IS NULL OR expected_users >= 0", name="ck_pilot_commercial_expected_users_nonnegative"),
        CheckConstraint("fully_loaded_hourly_cost IS NULL OR fully_loaded_hourly_cost >= 0", name="ck_pilot_commercial_hourly_cost_nonnegative"),
        CheckConstraint("adoption_rate IS NULL OR (adoption_rate >= 0 AND adoption_rate <= 1)", name="ck_pilot_commercial_adoption_rate_range"),
        CheckConstraint("pilot_fee_willingness IS NULL OR pilot_fee_willingness >= 0", name="ck_pilot_commercial_pilot_fee_nonnegative"),
        CheckConstraint("annual_wtp_min IS NULL OR annual_wtp_min >= 0", name="ck_pilot_commercial_wtp_min_nonnegative"),
        CheckConstraint("annual_wtp_max IS NULL OR annual_wtp_max >= 0", name="ck_pilot_commercial_wtp_max_nonnegative"),
        CheckConstraint("decision_timeline_days IS NULL OR decision_timeline_days >= 0", name="ck_pilot_commercial_timeline_nonnegative"),
        CheckConstraint("budget_status IN ('unknown','no_budget','exploring','budget_identified','approved')", name="ck_pilot_commercial_budget_status"),
        CheckConstraint("buying_stage IN ('problem_validation','solution_evaluation','pilot','business_case','procurement','contracting','no_interest')", name="ck_pilot_commercial_buying_stage"),
        CheckConstraint("deployment_preference IN ('unknown','cloud','private_cloud','on_prem')", name="ck_pilot_commercial_deployment_preference"),
        CheckConstraint("preferred_pricing_model IN ('unknown','pilot_fee','annual_platform','per_user','per_claim','usage')", name="ck_pilot_commercial_pricing_model"),
        CheckConstraint("respondent_outcome IN ('unknown','interested','pilot_extension','business_case','procurement','no_interest')", name="ck_pilot_commercial_outcome"),
        Index("ix_pilot_commercial_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("pilot_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    annual_claim_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fully_loaded_hourly_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    adoption_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")

    buyer_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    champion_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    budget_owner_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    procurement_owner_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    security_approver_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    budget_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")
    buying_stage: Mapped[str] = mapped_column(String(40), nullable=False, default="problem_validation", server_default="problem_validation")
    decision_timeline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    pilot_fee_willingness: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    annual_wtp_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    annual_wtp_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    preferred_pricing_model: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")

    deployment_preference: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")
    value_hypotheses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    must_have_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required_integrations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    security_requirements: Mapped[list | None] = mapped_column(JSON, nullable=True)
    blockers: Mapped[list | None] = mapped_column(JSON, nullable=True)

    respondent_outcome: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commercial_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
