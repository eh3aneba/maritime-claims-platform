"""bounded 100 percent Production AI outcome and enterprise readiness gate

Revision ID: 0056_ai_bounded_full_prod_outcomes
Revises: 0055_ai_bounded_full_prod
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_ai_bounded_full_prod_outcomes"
down_revision = "0055_ai_bounded_full_prod"
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
        "ai_bounded_full_production_outcome_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("bounded_full_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("near_universal_outcome_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80), server_default="bounded_full_outcome_v1", nullable=False),
        sa.Column("bounded_full_decision_hash", sa.String(64), nullable=False),
        sa.Column("bounded_full_completion_hash", sa.String(64), nullable=False),
        sa.Column("near_universal_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("near_universal_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("near_universal_decision_hash", sa.String(64), nullable=False),
        sa.Column("near_universal_completion_hash", sa.String(64), nullable=False),
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
        sa.Column("min_reviewed_runs", sa.Integer(), server_default="200", nullable=False),
        sa.Column("min_runs_per_workflow", sa.Integer(), server_default="50", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="300", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="1500", nullable=False),
        sa.Column("min_mean_usefulness_bps", sa.Integer(), server_default="9500", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="10", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9990", nullable=False),
        sa.Column("max_mean_review_seconds", sa.Integer(), server_default="195", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="12000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="325000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="40", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="350", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="350", nullable=False),
        sa.Column("min_business_workflows", sa.Integer(), server_default="15", nullable=False),
        sa.Column("min_tfta_improvement_bps", sa.Integer(), server_default="3500", nullable=False),
        sa.Column("min_triage_improvement_bps", sa.Integer(), server_default="4500", nullable=False),
        sa.Column("min_handler_effort_improvement_bps", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("min_business_usefulness_bps", sa.Integer(), server_default="9500", nullable=False),
        sa.Column("min_enterprise_controls", sa.Integer(), server_default="10", nullable=False),
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
        sa.ForeignKeyConstraint(["bounded_full_authorization_id"], ["ai_bounded_full_production_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["near_universal_outcome_assessment_id"], ["ai_near_universal_outcome_assessments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key", name="uq_ai_bfpo_org_key"),
        sa.UniqueConstraint("bounded_full_authorization_id", "attempt_number", name="uq_ai_bfpo_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_bfpo_attempt"),
        sa.CheckConstraint("rollout_percentage = 100", name="ck_ai_bfpo_rollout"),
        sa.CheckConstraint("min_reviewed_runs = 200 AND min_runs_per_workflow = 50", name="ck_ai_bfpo_volume"),
        sa.CheckConstraint("max_reject_rate_bps = 300 AND max_edit_rate_bps = 1500 AND min_mean_usefulness_bps = 9500", name="ck_ai_bfpo_quality_a"),
        sa.CheckConstraint("max_unsupported_output_rate_bps = 10 AND min_source_grounding_validity_bps = 9990 AND max_mean_review_seconds = 195", name="ck_ai_bfpo_quality_b"),
        sa.CheckConstraint("max_p95_latency_ms = 12000 AND max_mean_cost_microusd = 325000 AND max_quality_regression_bps = 40 AND max_latency_regression_bps = 350 AND max_cost_regression_bps = 350", name="ck_ai_bfpo_perf"),
        sa.CheckConstraint("min_business_workflows = 15 AND min_tfta_improvement_bps = 3500 AND min_triage_improvement_bps = 4500 AND min_handler_effort_improvement_bps = 3000 AND min_business_usefulness_bps = 9500", name="ck_ai_bfpo_business"),
        sa.CheckConstraint("min_enterprise_controls = 10", name="ck_ai_bfpo_enterprise"),
        sa.CheckConstraint("status IN ('collecting','review_ready','decision_ready','review_rejected','recommended','extended','stopped','failed')", name="ck_ai_bfpo_status"),
    )
    op.create_index("ix_ai_bfpo_org_status", "ai_bounded_full_production_outcome_assessments", ["organization_id", "status", "created_at"])
    op.create_index("ix_ai_bfpo_org", "ai_bounded_full_production_outcome_assessments", ["organization_id"])
    op.create_index("ix_ai_bfpo_auth", "ai_bounded_full_production_outcome_assessments", ["bounded_full_authorization_id"])

    op.create_table(
        "ai_bounded_full_production_outcome_observations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("bounded_full_run_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_bounded_full_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bounded_full_run_id"], ["ai_bounded_full_production_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "bounded_full_run_id", name="uq_ai_bfpo_obs_run"),
        sa.CheckConstraint("usefulness_rating BETWEEN 1 AND 5", name="ck_ai_bfpo_obs_usefulness"),
        sa.CheckConstraint("review_seconds BETWEEN 1 AND 3600", name="ck_ai_bfpo_obs_review_seconds"),
    )
    op.create_index("ix_ai_bfpo_obs_org", "ai_bounded_full_production_outcome_observations", ["organization_id", "assessment_id", "workflow_type"])
    op.create_index("ix_ai_bfpo_obs_run", "ai_bounded_full_production_outcome_observations", ["bounded_full_run_id"])

    op.create_table(
        "ai_bounded_full_production_outcome_business_evidence",
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_bounded_full_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_bfpob_key"),
        sa.CheckConstraint("handler_usefulness_rating BETWEEN 1 AND 5", name="ck_ai_bfpob_usefulness"),
        sa.CheckConstraint("baseline_tfta_seconds > 0 AND assisted_tfta_seconds > 0 AND baseline_triage_seconds > 0 AND assisted_triage_seconds > 0 AND baseline_handler_effort_seconds > 0 AND assisted_handler_effort_seconds > 0", name="ck_ai_bfpob_seconds"),
        sa.CheckConstraint("baseline_rework_count >= 0 AND assisted_rework_count >= 0 AND baseline_escalation_count >= 0 AND assisted_escalation_count >= 0 AND baseline_correction_count >= 0 AND assisted_correction_count >= 0", name="ck_ai_bfpob_counts"),
    )
    op.create_index("ix_ai_bfpob_org", "ai_bounded_full_production_outcome_business_evidence", ["organization_id", "assessment_id", "workflow_type"])
    op.create_index("ix_ai_bfpob_claim", "ai_bounded_full_production_outcome_business_evidence", ["claim_id"])

    op.create_table(
        "ai_bounded_full_production_outcome_enterprise_evidence",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("control_category", sa.String(80), nullable=False),
        sa.Column("evidence_key", sa.String(120), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_bounded_full_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "control_category", name="uq_ai_bfpoe_category"),
        sa.CheckConstraint("control_category IN ('kill_switch_rollback','monitor_alerting','audit_hash_traceability','tenant_isolation','privacy_data_protection','availability_recovery','change_control_integrity','unit_economics','human_escalation_ownership','incident_executive_ownership')", name="ck_ai_bfpoe_category"),
    )
    op.create_index("ix_ai_bfpoe_org", "ai_bounded_full_production_outcome_enterprise_evidence", ["organization_id", "assessment_id", "control_category"])

    op.create_table(
        "ai_bounded_full_production_outcome_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_role", sa.String(80), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_bounded_full_production_outcome_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role", name="uq_ai_bfpo_review_role"),
        sa.CheckConstraint("review_role IN ('security','privacy','product','operations','risk','claims_governance','ai_quality','legal_data_governance','business_owner','platform_reliability','independent_production_assurance','data_protection','executive_production_sponsor','enterprise_architecture_resilience')", name="ck_ai_bfpo_review_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_bfpo_review_action"),
    )
    op.create_index("ix_ai_bfpo_review_org", "ai_bounded_full_production_outcome_reviews", ["organization_id", "assessment_id", "review_role"])


def downgrade() -> None:
    op.drop_table("ai_bounded_full_production_outcome_reviews")
    op.drop_table("ai_bounded_full_production_outcome_enterprise_evidence")
    op.drop_table("ai_bounded_full_production_outcome_business_evidence")
    op.drop_table("ai_bounded_full_production_outcome_observations")
    op.drop_table("ai_bounded_full_production_outcome_assessments")
