"""private pilot outcome assessment and exit recommendation

Revision ID: 0041_ai_pilot_outcomes
Revises: 0040_ai_private_pilot
"""
import sqlalchemy as sa
from alembic import op

revision = "0041_ai_pilot_outcomes"
down_revision = "0040_ai_private_pilot"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_pilot_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(60),
                  server_default="private_pilot_exit_v1", nullable=False),
        sa.Column("min_run_count", sa.Integer(), server_default="6", nullable=False),
        sa.Column("min_ce_run_count", sa.Integer(), server_default="3", nullable=False),
        sa.Column("min_engine_run_count", sa.Integer(), server_default="3", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="5000", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(),
                  server_default="8000", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(),
                  server_default="600", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(),
                  server_default="30000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(),
                  server_default="500000", nullable=False),
        sa.Column("status", sa.String(30), server_default="collecting", nullable=False),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("failure_reasons", sa.JSON(), nullable=True),
        sa.Column("assessment_note", sa.Text(), nullable=True),
        sa.Column("assessment_hash", sa.String(64), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pilot_id"],
                                ["ai_private_pilot_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key",
                            name="uq_ai_pilot_outcome_org_key"),
        sa.UniqueConstraint("pilot_id", "attempt_number",
                            name="uq_ai_pilot_outcome_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_pilot_outcome_attempt"),
        sa.CheckConstraint("assessment_profile = 'private_pilot_exit_v1'",
                           name="ck_ai_pilot_outcome_profile"),
        sa.CheckConstraint("min_run_count = 6 AND min_ce_run_count = 3 "
                           "AND min_engine_run_count = 3",
                           name="ck_ai_pilot_outcome_sample"),
        sa.CheckConstraint("max_reject_rate_bps = 2000 AND max_edit_rate_bps = 5000 "
                           "AND min_mean_usefulness_bps = 8000",
                           name="ck_ai_pilot_outcome_quality"),
        sa.CheckConstraint("max_mean_review_seconds = 600 AND max_p95_latency_ms = 30000 "
                           "AND max_mean_cost_microusd = 500000",
                           name="ck_ai_pilot_outcome_operations"),
    )
    op.create_index("ix_ai_pilot_outcome_assessments_organization_id",
                    "ai_pilot_outcome_assessments", ["organization_id"])
    op.create_index("ix_ai_pilot_outcome_assessments_pilot_id",
                    "ai_pilot_outcome_assessments", ["pilot_id"])
    op.create_index("ix_ai_pilot_outcome_org_status",
                    "ai_pilot_outcome_assessments", ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_pilot_workflow_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_run_id", sa.Uuid(), nullable=False),
        sa.Column("observed_by_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_type", sa.String(100), nullable=False),
        sa.Column("usefulness_rating", sa.Integer(), nullable=False),
        sa.Column("review_seconds", sa.Integer(), nullable=False),
        sa.Column("workflow_completed", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("boundary_control_passed", sa.Boolean(),
                  server_default=sa.true(), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"],
                                ["ai_pilot_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pilot_run_id"],
                                ["ai_private_pilot_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "pilot_run_id",
                            name="uq_ai_pilot_observation_run"),
        sa.CheckConstraint("workflow_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_pilot_observation_workflow"),
        sa.CheckConstraint("usefulness_rating BETWEEN 1 AND 5",
                           name="ck_ai_pilot_observation_usefulness"),
        sa.CheckConstraint("review_seconds BETWEEN 1 AND 3600",
                           name="ck_ai_pilot_observation_review_time"),
    )
    op.create_index("ix_ai_pilot_workflow_observations_organization_id",
                    "ai_pilot_workflow_observations", ["organization_id"])
    op.create_index("ix_ai_pilot_workflow_observations_assessment_id",
                    "ai_pilot_workflow_observations", ["assessment_id"])
    op.create_index("ix_ai_pilot_workflow_observations_pilot_run_id",
                    "ai_pilot_workflow_observations", ["pilot_run_id"])
    op.create_index("ix_ai_pilot_observation_org_assessment",
                    "ai_pilot_workflow_observations",
                    ["organization_id", "assessment_id", "workflow_type"])

    op.create_table(
        "ai_pilot_outcome_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"],
                                ["ai_pilot_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role",
                            name="uq_ai_pilot_outcome_review_role"),
        sa.CheckConstraint("review_role IN ('product', 'quality', 'risk')",
                           name="ck_ai_pilot_outcome_review_role"),
        sa.CheckConstraint("action IN ('approve', 'reject')",
                           name="ck_ai_pilot_outcome_review_action"),
    )
    op.create_index("ix_ai_pilot_outcome_reviews_organization_id",
                    "ai_pilot_outcome_reviews", ["organization_id"])
    op.create_index("ix_ai_pilot_outcome_reviews_assessment_id",
                    "ai_pilot_outcome_reviews", ["assessment_id"])
    op.create_index("ix_ai_pilot_outcome_review_org",
                    "ai_pilot_outcome_reviews", ["organization_id", "assessment_id", "review_role"])


def downgrade() -> None:
    op.drop_index("ix_ai_pilot_outcome_review_org", table_name="ai_pilot_outcome_reviews")
    op.drop_index("ix_ai_pilot_outcome_reviews_assessment_id",
                  table_name="ai_pilot_outcome_reviews")
    op.drop_index("ix_ai_pilot_outcome_reviews_organization_id",
                  table_name="ai_pilot_outcome_reviews")
    op.drop_table("ai_pilot_outcome_reviews")
    op.drop_index("ix_ai_pilot_observation_org_assessment",
                  table_name="ai_pilot_workflow_observations")
    op.drop_index("ix_ai_pilot_workflow_observations_pilot_run_id",
                  table_name="ai_pilot_workflow_observations")
    op.drop_index("ix_ai_pilot_workflow_observations_assessment_id",
                  table_name="ai_pilot_workflow_observations")
    op.drop_index("ix_ai_pilot_workflow_observations_organization_id",
                  table_name="ai_pilot_workflow_observations")
    op.drop_table("ai_pilot_workflow_observations")
    op.drop_index("ix_ai_pilot_outcome_org_status", table_name="ai_pilot_outcome_assessments")
    op.drop_index("ix_ai_pilot_outcome_assessments_pilot_id",
                  table_name="ai_pilot_outcome_assessments")
    op.drop_index("ix_ai_pilot_outcome_assessments_organization_id",
                  table_name="ai_pilot_outcome_assessments")
    op.drop_table("ai_pilot_outcome_assessments")
