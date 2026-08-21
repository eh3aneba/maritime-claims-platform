"""Production-wide human-reviewed AI authorization

Revision ID: 0057_ai_production_wide
Revises: 0056_ai_bounded_full_prod_outcomes
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_ai_production_wide"
down_revision = "0056_ai_bounded_full_prod_outcomes"
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
        "ai_production_wide_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("bounded_full_outcome_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("authorization_key", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(30), server_default="production", nullable=False),
        sa.Column("authorization_mode", sa.String(80), server_default="production_wide_human_reviewed", nullable=False),
        sa.Column("bounded_full_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("bounded_full_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("bounded_full_decision_hash", sa.String(64), nullable=False),
        sa.Column("bounded_full_completion_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("allowed_document_types", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monitor_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("rollback_slo_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("eligibility_policy_version", sa.String(80), nullable=False),
        sa.Column("eligibility_policy_reference", sa.String(500), nullable=False),
        sa.Column("legal_basis_policy_reference", sa.String(500), nullable=False),
        sa.Column("data_minimization_policy_reference", sa.String(500), nullable=False),
        sa.Column("deployment_isolation_reference", sa.String(500), nullable=False),
        sa.Column("provider_project_reference", sa.String(500), nullable=False),
        sa.Column("credential_control_reference", sa.String(500), nullable=False),
        sa.Column("monitoring_reference", sa.String(500), nullable=False),
        sa.Column("incident_response_reference", sa.String(500), nullable=False),
        sa.Column("rollback_reference", sa.String(500), nullable=False),
        sa.Column("model_change_control_reference", sa.String(500), nullable=False),
        sa.Column("internal_audit_reference", sa.String(500), nullable=False),
        sa.Column("change_ticket_reference", sa.String(500), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(80), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bounded_full_outcome_assessment_id"], ["ai_bounded_full_production_outcome_assessments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "authorization_key", name="uq_ai_pwa_org_key"),
        sa.UniqueConstraint("bounded_full_outcome_assessment_id", "attempt_number", name="uq_ai_pwa_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_pwa_attempt"),
        sa.CheckConstraint("monitor_interval_minutes = 60 AND rollback_slo_minutes = 15", name="ck_ai_pwa_runtime"),
        sa.CheckConstraint("status IN ('pending_approvals','decision_ready','authorized','held','rejected','paused','revoked')", name="ck_ai_pwa_status"),
    )
    op.create_index("ix_ai_pwa_org_status", "ai_production_wide_authorizations", ["organization_id", "status", "created_at"])
    op.create_index("ix_ai_pwa_assessment", "ai_production_wide_authorizations", ["bounded_full_outcome_assessment_id"])

    op.create_table(
        "ai_production_wide_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(80), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_production_wide_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "approval_role", name="uq_ai_pwa_approval_role"),
        sa.CheckConstraint("approval_role IN ('security','privacy','product','operations','risk','claims_governance','ai_quality','legal_data_governance','business_owner','platform_reliability','independent_production_assurance','data_protection','executive_production_sponsor','enterprise_architecture_resilience','internal_audit_model_risk')", name="ck_ai_pwa_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_pwa_action"),
    )
    op.create_index("ix_ai_pwa_approval_org", "ai_production_wide_approvals", ["organization_id", "authorization_id"])

    op.create_table(
        "ai_production_eligibility_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("confidentiality_level", sa.String(30), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_production_wide_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "document_id", "policy_hash", name="uq_ai_pwe_doc_policy"),
    )
    op.create_index("ix_ai_pwe_org", "ai_production_eligibility_decisions", ["organization_id", "authorization_id", "eligible"])

    op.create_table(
        "ai_production_decision_logs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("eligibility_decision_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("run_key", sa.String(120), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("eligibility_policy_hash", sa.String(64), nullable=False),
        sa.Column("eligibility_decision_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="queued", nullable=False),
        sa.Column("human_review_action", sa.String(20), nullable=True),
        sa.Column("output_candidate_count", sa.Integer(), nullable=True),
        sa.Column("human_edit_count", sa.Integer(), nullable=True),
        sa.Column("unsupported_output_count", sa.Integer(), nullable=True),
        sa.Column("source_grounded_output_count", sa.Integer(), nullable=True),
        sa.Column("source_grounding_total_count", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("observed_provider_cost_microusd", sa.Integer(), nullable=True),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("run_hash", sa.String(64), nullable=False),
        sa.Column("review_hash", sa.String(64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_production_wide_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eligibility_decision_id"], ["ai_production_eligibility_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processing_job_id"], ["document_processing_jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("processing_job_id", name="uq_ai_pwdl_processing_job"),
        sa.UniqueConstraint("authorization_id", "run_key", name="uq_ai_pwdl_run_key"),
        sa.CheckConstraint("status IN ('queued','human_reviewed')", name="ck_ai_pwdl_status"),
        sa.CheckConstraint("human_review_action IS NULL OR human_review_action IN ('approve','edit','reject')", name="ck_ai_pwdl_action"),
    )
    op.create_index("ix_ai_pwdl_org", "ai_production_decision_logs", ["organization_id", "authorization_id", "status"])

    op.create_table(
        "ai_production_wide_monitors",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("initiated_by_id", sa.Uuid(), nullable=True),
        sa.Column("monitor_key", sa.String(120), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("monitor_hash", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("monitored_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_production_wide_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "monitor_key", name="uq_ai_pwm_monitor_key"),
        sa.CheckConstraint("status IN ('pass','fail')", name="ck_ai_pwm_status"),
    )
    op.create_index("ix_ai_pwm_org", "ai_production_wide_monitors", ["organization_id", "authorization_id", "monitored_at"])

    op.create_table(
        "ai_production_wide_incidents",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("reported_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reference", sa.String(500), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_production_wide_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_ai_pwi_severity"),
        sa.CheckConstraint("category IN ('privacy','security','quality','cost','availability','cross_tenant','reliability','other')", name="ck_ai_pwi_category"),
        sa.CheckConstraint("status IN ('open','resolved')", name="ck_ai_pwi_status"),
    )
    op.create_index("ix_ai_pwi_org", "ai_production_wide_incidents", ["organization_id", "authorization_id", "status"])


def downgrade() -> None:
    op.drop_table("ai_production_wide_incidents")
    op.drop_table("ai_production_wide_monitors")
    op.drop_table("ai_production_decision_logs")
    op.drop_table("ai_production_eligibility_decisions")
    op.drop_table("ai_production_wide_approvals")
    op.drop_table("ai_production_wide_authorizations")
