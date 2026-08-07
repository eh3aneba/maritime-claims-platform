"""pilot instrumentation and feedback

Revision ID: 0015_pilot_instrumentation
Revises: 0014_usability_hardening
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_pilot_instrumentation"
down_revision: Union[str, None] = "0014_usability_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pilot_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("participant_user_id", sa.Uuid(), nullable=True),
        sa.Column("facilitator_user_id", sa.Uuid(), nullable=True),
        sa.Column("participant_role", sa.String(length=100), server_default="claims_handler", nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("baseline_assessment_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active','completed','abandoned')", name="ck_pilot_sessions_status"),
        sa.CheckConstraint("baseline_assessment_minutes IS NULL OR baseline_assessment_minutes >= 0", name="ck_pilot_sessions_baseline_nonnegative"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["facilitator_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_sessions_org_started", "pilot_sessions", ["organization_id", "started_at"])
    op.create_index("ix_pilot_sessions_claim_status", "pilot_sessions", ["claim_id", "status"])
    op.create_index(op.f("ix_pilot_sessions_organization_id"), "pilot_sessions", ["organization_id"])
    op.create_index(op.f("ix_pilot_sessions_claim_id"), "pilot_sessions", ["claim_id"])
    op.create_index(op.f("ix_pilot_sessions_participant_user_id"), "pilot_sessions", ["participant_user_id"])

    op.create_table(
        "pilot_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="server", nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("event_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('server','browser')", name="ck_pilot_events_source"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_pilot_events_duration_nonnegative"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["pilot_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_events_session_created", "pilot_events", ["session_id", "created_at"])
    op.create_index("ix_pilot_events_org_type", "pilot_events", ["organization_id", "event_type"])
    op.create_index(op.f("ix_pilot_events_organization_id"), "pilot_events", ["organization_id"])
    op.create_index(op.f("ix_pilot_events_session_id"), "pilot_events", ["session_id"])
    op.create_index(op.f("ix_pilot_events_claim_id"), "pilot_events", ["claim_id"])

    op.create_table(
        "pilot_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), server_default="medium", nullable=False),
        sa.Column("verdict", sa.String(length=40), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("category IN ('usability','ai_quality','rules','workflow','feature_gap','value','missing_document','technical','financial')", name="ck_pilot_feedback_category"),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_pilot_feedback_severity"),
        sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_pilot_feedback_rating"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["pilot_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_feedback_session_created", "pilot_feedback", ["session_id", "created_at"])
    op.create_index("ix_pilot_feedback_org_category", "pilot_feedback", ["organization_id", "category"])
    op.create_index(op.f("ix_pilot_feedback_organization_id"), "pilot_feedback", ["organization_id"])
    op.create_index(op.f("ix_pilot_feedback_session_id"), "pilot_feedback", ["session_id"])
    op.create_index(op.f("ix_pilot_feedback_claim_id"), "pilot_feedback", ["claim_id"])


def downgrade() -> None:
    op.drop_table("pilot_feedback")
    op.drop_table("pilot_events")
    op.drop_table("pilot_sessions")
