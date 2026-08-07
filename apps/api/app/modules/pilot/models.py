from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func
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
