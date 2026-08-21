"""measured broader-production outcome and >50 percent readiness recommendation

Revision ID: 0047_ai_bp_outcome
Revises: 0046_ai_broader_prod
"""
import sqlalchemy as sa
from alembic import op

revision = "0047_ai_bp_outcome"
down_revision = "0046_ai_broader_prod"
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
        "ai_broader_production_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("broader_production_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80), server_default="broader_production_readiness_v1", nullable=False),
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
        sa.Column("min_reviewed_runs", sa.Integer(), server_default="40", nullable=False),
        sa.Column("min_runs_per_workflow", sa.Integer(), server_default="10", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="600", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="2500", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(), server_default="8800", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="50", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9950", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(), server_default="360", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="18000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="450000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="200", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="1000", nullable=False),
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
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["broader_production_authorization_id"], ["ai_broader_production_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key", name="uq_ai_bpo_org_key"),
        sa.UniqueConstraint("broader_production_authorization_id", "attempt_number", name="uq_ai_bpo_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_bpo_attempt"),
        sa.CheckConstraint("rollout_percentage BETWEEN 26 AND 50", name="ck_ai_bpo_rollout"),
        sa.CheckConstraint("min_reviewed_runs = 40 AND min_runs_per_workflow = 10", name="ck_ai_bpo_minimums"),
        sa.CheckConstraint("max_reject_rate_bps = 600 AND max_edit_rate_bps = 2500 AND min_mean_usefulness_bps = 8800", name="ck_ai_bpo_quality"),
        sa.CheckConstraint("max_unsupported_output_rate_bps = 50 AND min_source_grounding_validity_bps = 9950", name="ck_ai_bpo_grounding"),
        sa.CheckConstraint("max_mean_review_seconds = 360 AND max_p95_latency_ms = 18000 AND max_mean_cost_microusd = 450000", name="ck_ai_bpo_ops"),
        sa.CheckConstraint("max_quality_regression_bps = 200 AND max_latency_regression_bps = 1000 AND max_cost_regression_bps = 1000", name="ck_ai_bpo_trends"),
        sa.CheckConstraint("status IN ('collecting','review_ready','decision_ready','review_rejected','recommended','extended','stopped','failed')", name="ck_ai_bpo_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('review_rejected','recommend_next_broader_stage','extend_broader_production','stop_ai_progression')", name="ck_ai_bpo_result"),
    )
    op.create_index("ix_ai_bpo_org", "ai_broader_production_outcome_assessments", ["organization_id"])
    op.create_index("ix_ai_bpo_auth", "ai_broader_production_outcome_assessments", ["broader_production_authorization_id"])
    op.create_index("ix_ai_bpo_org_status", "ai_broader_production_outcome_assessments", ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_broader_production_outcome_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("broader_production_run_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_broader_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["broader_production_run_id"], ["ai_broader_production_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "broader_production_run_id", name="uq_ai_bpo_obs_run"),
        sa.CheckConstraint("usefulness_rating BETWEEN 1 AND 5", name="ck_ai_bpo_usefulness"),
        sa.CheckConstraint("review_seconds BETWEEN 1 AND 3600", name="ck_ai_bpo_review_secs"),
    )
    op.create_index("ix_ai_bpo_obs_assess", "ai_broader_production_outcome_observations", ["assessment_id"])
    op.create_index("ix_ai_bpo_obs_run", "ai_broader_production_outcome_observations", ["broader_production_run_id"])
    op.create_index("ix_ai_bpo_obs_org", "ai_broader_production_outcome_observations", ["organization_id", "assessment_id", "workflow_type"])

    op.create_table(
        "ai_broader_production_outcome_reviews",
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_broader_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role", name="uq_ai_bpo_review_role"),
        sa.CheckConstraint("review_role IN ('product','quality','risk','operations','security','claims_governance')", name="ck_ai_bpo_review_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_bpo_review_action"),
    )
    op.create_index("ix_ai_bpo_review_assess", "ai_broader_production_outcome_reviews", ["assessment_id"])
    op.create_index("ix_ai_bpo_review_org", "ai_broader_production_outcome_reviews", ["organization_id", "assessment_id", "review_role"])


def downgrade() -> None:
    op.drop_table("ai_broader_production_outcome_reviews")
    op.drop_table("ai_broader_production_outcome_observations")
    op.drop_table("ai_broader_production_outcome_assessments")
