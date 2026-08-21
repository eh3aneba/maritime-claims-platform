"""final Production AI readiness review

Revision ID: 0050_ai_final_readiness
Revises: 0049_ai_hc_outcome
"""
import sqlalchemy as sa
from alembic import op

revision = "0050_ai_final_readiness"
down_revision = "0049_ai_hc_outcome"
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
        "ai_final_production_readiness_assessments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("high_coverage_outcome_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("assessment_key", sa.String(120), nullable=False),
        sa.Column("assessment_profile", sa.String(80), server_default="final_production_ai_readiness_v1", nullable=False),
        sa.Column("high_coverage_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("high_coverage_outcome_decision_hash", sa.String(64), nullable=False),
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
        sa.Column("min_claim_workflows", sa.Integer(), server_default="10", nullable=False),
        sa.Column("min_tfta_improvement_bps", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("min_triage_improvement_bps", sa.Integer(), server_default="4000", nullable=False),
        sa.Column("min_handler_effort_improvement_bps", sa.Integer(), server_default="2500", nullable=False),
        sa.Column("min_handler_usefulness_bps", sa.Integer(), server_default="9000", nullable=False),
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
        sa.ForeignKeyConstraint(["high_coverage_outcome_assessment_id"], ["ai_high_coverage_outcome_assessments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_key", name="uq_ai_fpra_org_key"),
        sa.UniqueConstraint("high_coverage_outcome_assessment_id", "attempt_number", name="uq_ai_fpra_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_fpra_attempt"),
        sa.CheckConstraint("rollout_percentage BETWEEN 51 AND 75", name="ck_ai_fpra_rollout"),
        sa.CheckConstraint("min_claim_workflows = 10", name="ck_ai_fpra_claims"),
        sa.CheckConstraint("min_tfta_improvement_bps = 3000 AND min_triage_improvement_bps = 4000 AND min_handler_effort_improvement_bps = 2500 AND min_handler_usefulness_bps = 9000", name="ck_ai_fpra_value"),
        sa.CheckConstraint("status IN ('collecting','review_ready','decision_ready','review_rejected','recommended','extended','stopped','failed')", name="ck_ai_fpra_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('review_rejected','recommend_separate_final_production_authorization','extend_high_coverage_validation','stop_ai_progression')", name="ck_ai_fpra_result"),
    )
    op.create_index("ix_ai_fpra_org", "ai_final_production_readiness_assessments", ["organization_id"])
    op.create_index("ix_ai_fpra_outcome", "ai_final_production_readiness_assessments", ["high_coverage_outcome_assessment_id"])
    op.create_index("ix_ai_fpra_org_status", "ai_final_production_readiness_assessments", ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_final_production_readiness_claim_evidence",
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_final_production_readiness_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "evidence_key", name="uq_ai_fprc_key"),
        sa.CheckConstraint("workflow_type IN ('chief_engineer_report','engine_log')", name="ck_ai_fprc_workflow"),
        sa.CheckConstraint("baseline_tfta_seconds > 0 AND assisted_tfta_seconds > 0 AND baseline_triage_seconds > 0 AND assisted_triage_seconds > 0 AND baseline_handler_effort_seconds > 0 AND assisted_handler_effort_seconds > 0", name="ck_ai_fprc_times"),
        sa.CheckConstraint("baseline_rework_count >= 0 AND assisted_rework_count >= 0", name="ck_ai_fprc_rework"),
        sa.CheckConstraint("handler_usefulness_rating BETWEEN 1 AND 5", name="ck_ai_fprc_useful"),
    )
    op.create_index("ix_ai_fprc_assess", "ai_final_production_readiness_claim_evidence", ["assessment_id"])
    op.create_index("ix_ai_fprc_claim", "ai_final_production_readiness_claim_evidence", ["claim_id"])
    op.create_index("ix_ai_fprc_org", "ai_final_production_readiness_claim_evidence", ["organization_id", "assessment_id", "workflow_type"])

    op.create_table(
        "ai_final_production_readiness_control_evidence",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("control_key", sa.String(80), nullable=False),
        sa.Column("passed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_final_production_readiness_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "control_key", name="uq_ai_fprx_control"),
        sa.CheckConstraint("control_key IN ('kill_switch_rehearsal','fail_closed_no_fallback','audit_traceability','model_change_governance','bundle_rollback_target','unit_economics','operations_oncall_ownership','monitoring_retention_sustainability','privacy_access_control','data_retention_legal_basis')", name="ck_ai_fprx_control"),
    )
    op.create_index("ix_ai_fprx_assess", "ai_final_production_readiness_control_evidence", ["assessment_id"])
    op.create_index("ix_ai_fprx_org", "ai_final_production_readiness_control_evidence", ["organization_id", "assessment_id", "control_key"])

    op.create_table(
        "ai_final_production_readiness_reviews",
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
        sa.ForeignKeyConstraint(["assessment_id"], ["ai_final_production_readiness_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "review_role", name="uq_ai_fprr_role"),
        sa.CheckConstraint("review_role IN ('product','quality','risk','operations','security','privacy','claims_governance','ai_quality')", name="ck_ai_fprr_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_fprr_action"),
    )
    op.create_index("ix_ai_fprr_assess", "ai_final_production_readiness_reviews", ["assessment_id"])
    op.create_index("ix_ai_fprr_org", "ai_final_production_readiness_reviews", ["organization_id", "assessment_id", "review_role"])


def downgrade() -> None:
    op.drop_table("ai_final_production_readiness_reviews")
    op.drop_table("ai_final_production_readiness_control_evidence")
    op.drop_table("ai_final_production_readiness_claim_evidence")
    op.drop_table("ai_final_production_readiness_assessments")
