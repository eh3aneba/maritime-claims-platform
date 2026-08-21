"""measured near-universal Production AI outcome gate

Revision ID: 0054_ai_near_univ_outcome
Revises: 0053_ai_near_universal
"""
import sqlalchemy as sa
from alembic import op

revision = "0054_ai_near_univ_outcome"
down_revision = "0053_ai_near_universal"
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
        "ai_near_universal_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("near_universal_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80), server_default="near_universal_outcome_v1", nullable=False),
        sa.Column("near_universal_decision_hash", sa.String(64), nullable=False),
        sa.Column("near_universal_completion_hash", sa.String(64), nullable=False),
        sa.Column("outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("outcome_decision_hash", sa.String(64), nullable=False),
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
        sa.Column("min_reviewed_runs", sa.Integer(), server_default="160", nullable=False),
        sa.Column("min_runs_per_workflow", sa.Integer(), server_default="40", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="350", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="1600", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(), server_default="9400", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="15", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9985", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(), server_default="210", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="13000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="350000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="50", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="400", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="400", nullable=False),
        sa.Column("min_business_workflows", sa.Integer(), server_default="12", nullable=False),
        sa.Column("min_tfta_improvement_bps", sa.Integer(), server_default="3500", nullable=False),
        sa.Column("min_triage_improvement_bps", sa.Integer(), server_default="4500", nullable=False),
        sa.Column("min_handler_effort_improvement_bps", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("min_business_usefulness_bps", sa.Integer(), server_default="9400", nullable=False),
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
        sa.ForeignKeyConstraint(["near_universal_authorization_id"], ["ai_near_universal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key", name="uq_ai_nuo_org_key"),
        sa.UniqueConstraint("near_universal_authorization_id", "attempt_number", name="uq_ai_nuo_attempt"),
        sa.CheckConstraint("rollout_percentage >= 91 AND rollout_percentage <= 99", name="ck_ai_nuo_rollout_91_99"),
    )
    op.create_index("ix_ai_nuo_org_status", "ai_near_universal_outcome_assessments", ["organization_id", "status", "created_at"])
    op.create_index("ix_ai_near_universal_outcome_assessments_organization_id", "ai_near_universal_outcome_assessments", ["organization_id"])
    op.create_index("ix_ai_nuo_auth", "ai_near_universal_outcome_assessments", ["near_universal_authorization_id"])

    op.create_table(
        "ai_near_universal_outcome_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("near_universal_run_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_near_universal_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["near_universal_run_id"], ["ai_near_universal_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "near_universal_run_id", name="uq_ai_nuo_obs_run"),
    )
    op.create_index("ix_ai_nuo_obs_org", "ai_near_universal_outcome_observations", ["organization_id", "assessment_id", "workflow_type"])
    op.create_index("ix_ai_near_universal_outcome_observations_organization_id", "ai_near_universal_outcome_observations", ["organization_id"])
    op.create_index("ix_ai_near_universal_outcome_observations_assessment_id", "ai_near_universal_outcome_observations", ["assessment_id"])
    op.create_index("ix_ai_near_universal_outcome_observations_near_universal_run_id", "ai_near_universal_outcome_observations", ["near_universal_run_id"])

    op.create_table(
        "ai_near_universal_outcome_business_evidence",
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
        sa.Column("baseline_escalation_count", sa.Integer(), nullable=False),
        sa.Column("assisted_escalation_count", sa.Integer(), nullable=False),
        sa.Column("baseline_correction_count", sa.Integer(), nullable=False),
        sa.Column("assisted_correction_count", sa.Integer(), nullable=False),
        sa.Column("handler_usefulness_rating", sa.Integer(), nullable=False),
        sa.Column("final_claim_decision_human_owned", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_near_universal_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_nuob_key"),
    )
    op.create_index("ix_ai_nuob_org", "ai_near_universal_outcome_business_evidence", ["organization_id", "assessment_id", "workflow_type"])
    op.create_index("ix_ai_near_universal_outcome_business_evidence_organization_id", "ai_near_universal_outcome_business_evidence", ["organization_id"])
    op.create_index("ix_ai_near_universal_outcome_business_evidence_assessment_id", "ai_near_universal_outcome_business_evidence", ["assessment_id"])
    op.create_index("ix_ai_near_universal_outcome_business_evidence_claim_id", "ai_near_universal_outcome_business_evidence", ["claim_id"])

    op.create_table(
        "ai_near_universal_outcome_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_role", sa.String(60), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_near_universal_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role", name="uq_ai_nuo_review_role"),
    )
    op.create_index("ix_ai_nuo_review_org", "ai_near_universal_outcome_reviews", ["organization_id", "assessment_id", "review_role"])
    op.create_index("ix_ai_near_universal_outcome_reviews_organization_id", "ai_near_universal_outcome_reviews", ["organization_id"])
    op.create_index("ix_ai_near_universal_outcome_reviews_assessment_id", "ai_near_universal_outcome_reviews", ["assessment_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_near_universal_outcome_reviews_assessment_id", table_name="ai_near_universal_outcome_reviews")
    op.drop_index("ix_ai_near_universal_outcome_reviews_organization_id", table_name="ai_near_universal_outcome_reviews")
    op.drop_index("ix_ai_nuo_review_org", table_name="ai_near_universal_outcome_reviews")
    op.drop_table("ai_near_universal_outcome_reviews")
    op.drop_index("ix_ai_near_universal_outcome_business_evidence_claim_id", table_name="ai_near_universal_outcome_business_evidence")
    op.drop_index("ix_ai_near_universal_outcome_business_evidence_assessment_id", table_name="ai_near_universal_outcome_business_evidence")
    op.drop_index("ix_ai_near_universal_outcome_business_evidence_organization_id", table_name="ai_near_universal_outcome_business_evidence")
    op.drop_index("ix_ai_nuob_org", table_name="ai_near_universal_outcome_business_evidence")
    op.drop_table("ai_near_universal_outcome_business_evidence")
    op.drop_index("ix_ai_near_universal_outcome_observations_near_universal_run_id", table_name="ai_near_universal_outcome_observations")
    op.drop_index("ix_ai_near_universal_outcome_observations_assessment_id", table_name="ai_near_universal_outcome_observations")
    op.drop_index("ix_ai_near_universal_outcome_observations_organization_id", table_name="ai_near_universal_outcome_observations")
    op.drop_index("ix_ai_nuo_obs_org", table_name="ai_near_universal_outcome_observations")
    op.drop_table("ai_near_universal_outcome_observations")
    op.drop_index("ix_ai_nuo_auth", table_name="ai_near_universal_outcome_assessments")
    op.drop_index("ix_ai_near_universal_outcome_assessments_organization_id", table_name="ai_near_universal_outcome_assessments")
    op.drop_index("ix_ai_nuo_org_status", table_name="ai_near_universal_outcome_assessments")
    op.drop_table("ai_near_universal_outcome_assessments")
