"""measured limited-production outcome and graduation recommendation

Revision ID: 0043_ai_limited_outcome
Revises: 0042_ai_limited_production
"""
import sqlalchemy as sa
from alembic import op

revision = "0043_ai_limited_outcome"
down_revision = "0042_ai_limited_production"
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
        "ai_limited_production_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80),
                  server_default="limited_production_graduation_v1", nullable=False),
        sa.Column("authorization_decision_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="3500", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(),
                  server_default="8400", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(),
                  server_default="100", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(),
                  server_default="9900", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(),
                  server_default="480", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(),
                  server_default="20000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(),
                  server_default="500000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(),
                  server_default="500", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(),
                  server_default="2000", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(),
                  server_default="2000", nullable=False),
        sa.Column("status", sa.String(30), server_default="collecting", nullable=False),
        sa.Column("outcome", sa.String(60), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["authorization_id"],
            ["ai_limited_production_authorizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key",
                            name="uq_ai_limited_outcome_org_key"),
        sa.UniqueConstraint("authorization_id", "attempt_number",
                            name="uq_ai_limited_outcome_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_limited_outcome_attempt"),
        sa.CheckConstraint("rollout_percentage BETWEEN 1 AND 10",
                           name="ck_ai_limited_outcome_rollout"),
        sa.CheckConstraint(
            "max_reject_rate_bps = 1000 AND max_edit_rate_bps = 3500 "
            "AND min_mean_usefulness_bps = 8400 "
            "AND max_unsupported_output_rate_bps = 100 "
            "AND min_source_grounding_validity_bps = 9900 "
            "AND max_mean_review_seconds = 480 "
            "AND max_p95_latency_ms = 20000 "
            "AND max_mean_cost_microusd = 500000 "
            "AND max_quality_regression_bps = 500 "
            "AND max_latency_regression_bps = 2000 "
            "AND max_cost_regression_bps = 2000",
            name="ck_ai_limited_outcome_thresholds",
        ),
        sa.CheckConstraint(
            "status IN ('collecting', 'review_ready', 'failed', 'decision_ready', "
            "'review_rejected', 'recommended', 'extended', 'stopped')",
            name="ck_ai_limited_outcome_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('review_rejected', "
            "'recommend_graduation_stage', 'extend_limited_production_evaluation', "
            "'stop_ai_progression')",
            name="ck_ai_limited_outcome_result",
        ),
    )
    op.create_index(
        "ix_ai_limited_outcome_assessment_org",
        "ai_limited_production_outcome_assessments",
        ["organization_id"],
    )
    op.create_index(
        "ix_ai_limited_outcome_assessment_auth",
        "ai_limited_production_outcome_assessments",
        ["authorization_id"],
    )
    op.create_index(
        "ix_ai_limited_outcome_org_status",
        "ai_limited_production_outcome_assessments",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "ai_limited_production_outcome_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("limited_run_id", sa.Uuid(), nullable=False),
        sa.Column("observed_by_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_type", sa.String(100), nullable=False),
        sa.Column("usefulness_rating", sa.Integer(), nullable=False),
        sa.Column("review_seconds", sa.Integer(), nullable=False),
        sa.Column("unsupported_output_count", sa.Integer(), nullable=False),
        sa.Column("source_grounded_output_count", sa.Integer(), nullable=False),
        sa.Column("source_grounding_total_count", sa.Integer(), nullable=False),
        sa.Column("workflow_completed", sa.Boolean(),
                  server_default=sa.text("true"), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["ai_limited_production_outcome_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["limited_run_id"], ["ai_limited_production_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "limited_run_id",
                            name="uq_ai_limited_outcome_observation_run"),
        sa.CheckConstraint("workflow_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_limited_outcome_observation_type"),
        sa.CheckConstraint("usefulness_rating BETWEEN 1 AND 5",
                           name="ck_ai_limited_outcome_usefulness"),
        sa.CheckConstraint("review_seconds BETWEEN 1 AND 3600",
                           name="ck_ai_limited_outcome_review_seconds"),
        sa.CheckConstraint(
            "unsupported_output_count >= 0 AND source_grounded_output_count >= 0 "
            "AND source_grounding_total_count >= 0 "
            "AND source_grounded_output_count <= source_grounding_total_count",
            name="ck_ai_limited_outcome_grounding_counts",
        ),
    )
    op.create_index(
        "ix_ai_limited_outcome_observation_org",
        "ai_limited_production_outcome_observations",
        ["organization_id", "assessment_id", "workflow_type"],
    )
    op.create_index(
        "ix_ai_limited_outcome_observation_run",
        "ai_limited_production_outcome_observations",
        ["limited_run_id"],
    )

    op.create_table(
        "ai_limited_production_outcome_reviews",
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
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["ai_limited_production_outcome_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role",
                            name="uq_ai_limited_outcome_review_role"),
        sa.CheckConstraint(
            "review_role IN ('product', 'quality', 'risk', 'operations')",
            name="ck_ai_limited_outcome_review_role",
        ),
        sa.CheckConstraint("action IN ('approve', 'reject')",
                           name="ck_ai_limited_outcome_review_action"),
    )
    op.create_index(
        "ix_ai_limited_outcome_review_org",
        "ai_limited_production_outcome_reviews",
        ["organization_id", "assessment_id", "review_role"],
    )


def downgrade() -> None:
    op.drop_table("ai_limited_production_outcome_reviews")
    op.drop_table("ai_limited_production_outcome_observations")
    op.drop_table("ai_limited_production_outcome_assessments")
