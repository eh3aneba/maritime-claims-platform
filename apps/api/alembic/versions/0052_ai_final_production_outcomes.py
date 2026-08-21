"""measured final-production outcome and >90 readiness recommendation

Revision ID: 0052_ai_final_prod_outcome
Revises: 0051_ai_final_prod
"""
import sqlalchemy as sa
from alembic import op

revision = "0052_ai_final_prod_outcome"
down_revision = "0051_ai_final_prod"
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
        "ai_final_production_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("final_production_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80), server_default="final_production_outcome_v1", nullable=False),
        sa.Column("final_production_decision_hash", sa.String(64), nullable=False),
        sa.Column("final_production_completion_hash", sa.String(64), nullable=False),
        sa.Column("final_readiness_assessment_hash", sa.String(64), nullable=False),
        sa.Column("final_readiness_decision_hash", sa.String(64), nullable=False),
        sa.Column("high_coverage_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("high_coverage_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("high_coverage_decision_hash", sa.String(64), nullable=False),
        sa.Column("high_coverage_completion_hash", sa.String(64), nullable=False),
        sa.Column("broader_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("broader_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("broader_production_decision_hash", sa.String(64), nullable=False),
        sa.Column("scale_readiness_assessment_hash", sa.String(64), nullable=False),
        sa.Column("scale_readiness_decision_hash", sa.String(64), nullable=False),
        sa.Column("scale_up_decision_hash", sa.String(64), nullable=False),
        sa.Column("inherited_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("inherited_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("allowed_document_types", sa.JSON(), nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("max_documents", sa.Integer(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_provider_runs", sa.Integer(), nullable=False),
        sa.Column("min_reviewed_runs", sa.Integer(), server_default="120", nullable=False),
        sa.Column("min_runs_per_workflow", sa.Integer(), server_default="30", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="400", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="1800", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(), server_default="9200", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="20", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9980", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(), server_default="240", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="14000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="375000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="75", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="500", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="500", nullable=False),
        sa.Column("min_business_workflows", sa.Integer(), server_default="10", nullable=False),
        sa.Column("min_tfta_improvement_bps", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("min_triage_improvement_bps", sa.Integer(), server_default="4000", nullable=False),
        sa.Column("min_handler_effort_improvement_bps", sa.Integer(), server_default="2500", nullable=False),
        sa.Column("min_business_usefulness_bps", sa.Integer(), server_default="9200", nullable=False),
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
        sa.ForeignKeyConstraint(["final_production_authorization_id"], ["ai_final_production_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key", name="uq_ai_fpo_org_key"),
        sa.UniqueConstraint("final_production_authorization_id", "attempt_number", name="uq_ai_fpo_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_fpo_attempt"),
        sa.CheckConstraint("rollout_percentage BETWEEN 76 AND 90", name="ck_ai_fpo_rollout"),
        sa.CheckConstraint("min_reviewed_runs = 120 AND min_runs_per_workflow = 30", name="ck_ai_fpo_volume"),
        sa.CheckConstraint("max_reject_rate_bps = 400 AND max_edit_rate_bps = 1800 AND min_mean_usefulness_bps = 9200", name="ck_ai_fpo_review_quality"),
        sa.CheckConstraint("max_unsupported_output_rate_bps = 20 AND min_source_grounding_validity_bps = 9980", name="ck_ai_fpo_grounding"),
        sa.CheckConstraint("max_mean_review_seconds = 240 AND max_p95_latency_ms = 14000 AND max_mean_cost_microusd = 375000", name="ck_ai_fpo_efficiency"),
        sa.CheckConstraint("max_quality_regression_bps = 75 AND max_latency_regression_bps = 500 AND max_cost_regression_bps = 500", name="ck_ai_fpo_regression"),
        sa.CheckConstraint("min_business_workflows = 10 AND min_tfta_improvement_bps = 3000 AND min_triage_improvement_bps = 4000 AND min_handler_effort_improvement_bps = 2500 AND min_business_usefulness_bps = 9200", name="ck_ai_fpo_business"),
        sa.CheckConstraint("status IN ('collecting','review_ready','decision_ready','review_rejected','recommended','extended','stopped','failed')", name="ck_ai_fpo_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('review_rejected','recommend_separate_91_100_authorization_review','extend_final_production_76_90','stop_ai_progression')", name="ck_ai_fpo_result"),
    )
    op.create_index("ix_ai_fpo_org", "ai_final_production_outcome_assessments", ["organization_id"])
    op.create_index("ix_ai_fpo_auth", "ai_final_production_outcome_assessments", ["final_production_authorization_id"])
    op.create_index("ix_ai_fpo_org_status", "ai_final_production_outcome_assessments", ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_final_production_outcome_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("final_production_run_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_final_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["final_production_run_id"], ["ai_final_production_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "final_production_run_id", name="uq_ai_fpo_obs_run"),
        sa.CheckConstraint("workflow_type IN ('chief_engineer_report','engine_log')", name="ck_ai_fpo_obs_workflow"),
        sa.CheckConstraint("usefulness_rating BETWEEN 1 AND 5", name="ck_ai_fpo_obs_useful"),
        sa.CheckConstraint("review_seconds BETWEEN 1 AND 3600", name="ck_ai_fpo_obs_review"),
    )
    op.create_index("ix_ai_fpo_obs_assess", "ai_final_production_outcome_observations", ["assessment_id"])
    op.create_index("ix_ai_fpo_obs_run", "ai_final_production_outcome_observations", ["final_production_run_id"])
    op.create_index("ix_ai_fpo_obs_org", "ai_final_production_outcome_observations", ["organization_id", "assessment_id", "workflow_type"])

    op.create_table(
        "ai_final_production_outcome_business_evidence",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_key", sa.String(120), nullable=False),
        sa.Column("workflow_type", sa.String(100), nullable=False),
        sa.Column("baseline_tfta_seconds", sa.Integer(), nullable=False),
        sa.Column("assisted_tfta_seconds", sa.Integer(), nullable=False),
        sa.Column("baseline_triage_seconds", sa.Integer(), nullable=False),
        sa.Column("assisted_triage_seconds", sa.Integer(), nullable=False),
        sa.Column("baseline_handler_effort_seconds", sa.Integer(), nullable=False),
        sa.Column("assisted_handler_effort_seconds", sa.Integer(), nullable=False),
        sa.Column("baseline_rework_count", sa.Integer(), nullable=False),
        sa.Column("assisted_rework_count", sa.Integer(), nullable=False),
        sa.Column("handler_usefulness_rating", sa.Integer(), nullable=False),
        sa.Column("final_claim_decision_human_owned", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_final_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_fpob_key"),
        sa.CheckConstraint("workflow_type IN ('chief_engineer_report','engine_log')", name="ck_ai_fpob_workflow"),
        sa.CheckConstraint("baseline_tfta_seconds > 0 AND assisted_tfta_seconds > 0 AND baseline_triage_seconds > 0 AND assisted_triage_seconds > 0 AND baseline_handler_effort_seconds > 0 AND assisted_handler_effort_seconds > 0", name="ck_ai_fpob_times"),
        sa.CheckConstraint("baseline_rework_count >= 0 AND assisted_rework_count >= 0", name="ck_ai_fpob_rework"),
        sa.CheckConstraint("handler_usefulness_rating BETWEEN 1 AND 5", name="ck_ai_fpob_useful"),
    )
    op.create_index("ix_ai_fpob_assess", "ai_final_production_outcome_business_evidence", ["assessment_id"])
    op.create_index("ix_ai_fpob_claim", "ai_final_production_outcome_business_evidence", ["claim_id"])
    op.create_index("ix_ai_fpob_org", "ai_final_production_outcome_business_evidence", ["organization_id", "assessment_id", "workflow_type"])

    op.create_table(
        "ai_final_production_outcome_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_role", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_final_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role", name="uq_ai_fpo_review_role"),
        sa.CheckConstraint("review_role IN ('product','quality','risk','operations','security','privacy','claims_governance','ai_quality','legal_data_governance','business_owner')", name="ck_ai_fpo_review_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_fpo_review_action"),
    )
    op.create_index("ix_ai_fpo_review_assess", "ai_final_production_outcome_reviews", ["assessment_id"])
    op.create_index("ix_ai_fpo_review_org", "ai_final_production_outcome_reviews", ["organization_id", "assessment_id", "review_role"])


def downgrade() -> None:
    op.drop_table("ai_final_production_outcome_reviews")
    op.drop_table("ai_final_production_outcome_business_evidence")
    op.drop_table("ai_final_production_outcome_observations")
    op.drop_table("ai_final_production_outcome_assessments")
