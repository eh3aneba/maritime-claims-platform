"""measured high-coverage outcome and final-readiness recommendation

Revision ID: 0049_ai_hc_outcome
Revises: 0048_ai_high_coverage
"""
import sqlalchemy as sa
from alembic import op

revision = "0049_ai_hc_outcome"
down_revision = "0048_ai_high_coverage"
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_high_coverage_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("high_coverage_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80), server_default="high_coverage_final_readiness_v1", nullable=False),
        sa.Column("high_coverage_decision_hash", sa.String(64), nullable=False),
        sa.Column("high_coverage_completion_hash", sa.String(64), nullable=False),
        sa.Column("broader_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("broader_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("broader_production_decision_hash", sa.String(64), nullable=False),
        sa.Column("readiness_assessment_hash", sa.String(64), nullable=False),
        sa.Column("readiness_decision_hash", sa.String(64), nullable=False),
        sa.Column("scale_up_decision_hash", sa.String(64), nullable=False),
        sa.Column("inherited_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("inherited_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("min_reviewed_runs", sa.Integer(), server_default="80", nullable=False),
        sa.Column("min_runs_per_workflow", sa.Integer(), server_default="20", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="500", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(), server_default="9000", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="25", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9975", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="15000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="400000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="100", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="750", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="750", nullable=False),
        sa.Column("status", sa.String(30), server_default="collecting", nullable=False),
        sa.Column("outcome", sa.String(80), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("failure_reasons", sa.JSON(), nullable=True),
        sa.Column("assessment_note", sa.Text(), nullable=True),
        sa.Column("assessment_hash", sa.String(64), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["high_coverage_authorization_id"], ["ai_high_coverage_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key", name="uq_ai_hco_org_key"),
        sa.UniqueConstraint("high_coverage_authorization_id", "attempt_number", name="uq_ai_hco_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_hco_attempt"),
        sa.CheckConstraint("rollout_percentage BETWEEN 51 AND 75", name="ck_ai_hco_rollout"),
        sa.CheckConstraint("min_reviewed_runs = 80 AND min_runs_per_workflow = 20", name="ck_ai_hco_minimums"),
        sa.CheckConstraint("max_reject_rate_bps = 500 AND max_edit_rate_bps = 2000 AND min_mean_usefulness_bps = 9000", name="ck_ai_hco_quality"),
        sa.CheckConstraint("max_unsupported_output_rate_bps = 25 AND min_source_grounding_validity_bps = 9975", name="ck_ai_hco_grounding"),
        sa.CheckConstraint("max_mean_review_seconds = 300 AND max_p95_latency_ms = 15000 AND max_mean_cost_microusd = 400000", name="ck_ai_hco_ops"),
        sa.CheckConstraint("max_quality_regression_bps = 100 AND max_latency_regression_bps = 750 AND max_cost_regression_bps = 750", name="ck_ai_hco_trends"),
        sa.CheckConstraint("status IN ('collecting','review_ready','decision_ready','review_rejected','recommended','extended','stopped','failed')", name="ck_ai_hco_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('review_rejected','recommend_final_production_readiness_review','extend_high_coverage_51_75','stop_ai_progression')", name="ck_ai_hco_result"),
    )
    op.create_index("ix_ai_hco_org", "ai_high_coverage_outcome_assessments", ["organization_id"])
    op.create_index("ix_ai_hco_auth", "ai_high_coverage_outcome_assessments", ["high_coverage_authorization_id"])
    op.create_index("ix_ai_hco_org_status", "ai_high_coverage_outcome_assessments", ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_high_coverage_outcome_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("high_coverage_run_id", sa.Uuid(), nullable=False),
        sa.Column("observed_by_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_type", sa.String(100), nullable=False),
        sa.Column("usefulness_rating", sa.Integer(), nullable=False),
        sa.Column("review_seconds", sa.Integer(), nullable=False),
        sa.Column("workflow_completed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_high_coverage_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["high_coverage_run_id"], ["ai_high_coverage_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "high_coverage_run_id", name="uq_ai_hco_obs_run"),
        sa.CheckConstraint("usefulness_rating BETWEEN 1 AND 5", name="ck_ai_hco_usefulness"),
        sa.CheckConstraint("review_seconds BETWEEN 1 AND 3600", name="ck_ai_hco_review_secs"),
    )
    op.create_index("ix_ai_hco_obs_assess", "ai_high_coverage_outcome_observations", ["assessment_id"])
    op.create_index("ix_ai_hco_obs_run", "ai_high_coverage_outcome_observations", ["high_coverage_run_id"])
    op.create_index("ix_ai_hco_obs_org", "ai_high_coverage_outcome_observations", ["organization_id", "assessment_id", "workflow_type"])

    op.create_table(
        "ai_high_coverage_outcome_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_role", sa.String(40), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_high_coverage_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role", name="uq_ai_hco_review_role"),
        sa.CheckConstraint("review_role IN ('product','quality','risk','operations','security','claims_governance','ai_quality')", name="ck_ai_hco_review_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_hco_review_action"),
    )
    op.create_index("ix_ai_hco_review_assess", "ai_high_coverage_outcome_reviews", ["assessment_id"])
    op.create_index("ix_ai_hco_review_org", "ai_high_coverage_outcome_reviews", ["organization_id", "assessment_id", "review_role"])


def downgrade() -> None:
    op.drop_table("ai_high_coverage_outcome_reviews")
    op.drop_table("ai_high_coverage_outcome_observations")
    op.drop_table("ai_high_coverage_outcome_assessments")
