"""bounded 100 percent Production AI cohort authorization

Revision ID: 0055_ai_bounded_full_prod
Revises: 0054_ai_near_univ_outcome
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_ai_bounded_full_prod"
down_revision = "0054_ai_near_univ_outcome"
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
        "ai_bounded_full_production_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("near_universal_outcome_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("near_universal_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("authorization_key", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(30), server_default="production", nullable=False),
        sa.Column("authorization_mode", sa.String(80), server_default="bounded_full_100_percent", nullable=False),
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
        sa.Column("previous_rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), server_default="100", nullable=False),
        sa.Column("previous_max_claims", sa.Integer(), nullable=False),
        sa.Column("previous_max_documents", sa.Integer(), nullable=False),
        sa.Column("previous_max_users", sa.Integer(), nullable=False),
        sa.Column("previous_max_provider_runs", sa.Integer(), nullable=False),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("max_documents", sa.Integer(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_provider_runs", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rollback_slo_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("monitor_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="350", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="1600", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="15", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9985", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="13000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="350000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="50", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="400", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="400", nullable=False),
        sa.Column("deployment_isolation_reference", sa.String(500), nullable=False),
        sa.Column("provider_project_reference", sa.String(500), nullable=False),
        sa.Column("credential_control_reference", sa.String(500), nullable=False),
        sa.Column("privacy_legal_reference", sa.String(500), nullable=False),
        sa.Column("monitoring_reference", sa.String(500), nullable=False),
        sa.Column("incident_response_reference", sa.String(500), nullable=False),
        sa.Column("rollback_reference", sa.String(500), nullable=False),
        sa.Column("platform_reliability_reference", sa.String(500), nullable=False),
        sa.Column("data_protection_reference", sa.String(500), nullable=False),
        sa.Column("executive_sponsor_reference", sa.String(500), nullable=False),
        sa.Column("change_ticket_reference", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(80), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("completion_hash", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["near_universal_outcome_assessment_id"], ["ai_near_universal_outcome_assessments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["near_universal_authorization_id"], ["ai_near_universal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "authorization_key", name="uq_ai_bfp_org_key"),
        sa.UniqueConstraint("near_universal_outcome_assessment_id", "attempt_number", name="uq_ai_bfp_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_bfp_attempt"),
        sa.CheckConstraint("previous_rollout_percentage BETWEEN 91 AND 99", name="ck_ai_bfp_prev_rollout"),
        sa.CheckConstraint("rollout_percentage = 100", name="ck_ai_bfp_rollout"),
        sa.CheckConstraint("max_claims BETWEEN 1 AND 120 AND max_documents BETWEEN 1 AND 360 AND max_users BETWEEN 1 AND 120 AND max_provider_runs BETWEEN 1 AND 2000", name="ck_ai_bfp_caps"),
        sa.CheckConstraint("rollback_slo_minutes = 15 AND monitor_interval_minutes = 60", name="ck_ai_bfp_runtime"),
        sa.CheckConstraint("max_reject_rate_bps = 350 AND max_edit_rate_bps = 1600 AND max_unsupported_output_rate_bps = 15 AND min_source_grounding_validity_bps = 9985", name="ck_ai_bfp_quality"),
        sa.CheckConstraint("max_p95_latency_ms = 13000 AND max_mean_cost_microusd = 350000 AND max_quality_regression_bps = 50 AND max_latency_regression_bps = 400 AND max_cost_regression_bps = 400", name="ck_ai_bfp_perf"),
        sa.CheckConstraint("status IN ('pending_approvals','decision_ready','authorized','held','rejected','paused','revoked','completed')", name="ck_ai_bfp_status"),
    )
    op.create_index("ix_ai_bfp_org_status", "ai_bounded_full_production_authorizations", ["organization_id", "status", "created_at"])
    op.create_index("ix_ai_bfp_org", "ai_bounded_full_production_authorizations", ["organization_id"])
    op.create_index("ix_ai_bfp_outcome", "ai_bounded_full_production_authorizations", ["near_universal_outcome_assessment_id"])
    op.create_index("ix_ai_bfp_near", "ai_bounded_full_production_authorizations", ["near_universal_authorization_id"])

    op.create_table(
        "ai_bounded_full_production_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(60), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_bounded_full_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "approval_role", name="uq_ai_bfp_approval_role"),
        sa.CheckConstraint("approval_role IN ('security','privacy','product','operations','risk','claims_governance','ai_quality','legal_data_governance','business_owner','platform_reliability','independent_production_assurance','data_protection','executive_production_sponsor')", name="ck_ai_bfp_approval_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_bfp_approval_action"),
    )
    op.create_index("ix_ai_bfp_approval_org", "ai_bounded_full_production_approvals", ["organization_id", "authorization_id"])

    op.create_table(
        "ai_bounded_full_production_document_eligibility",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attested_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attestation_number", sa.Integer(), nullable=False),
        sa.Column("rollout_bucket", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("confidentiality_level", sa.String(30), nullable=False),
        sa.Column("legal_basis_reference", sa.String(500), nullable=False),
        sa.Column("data_minimization_reference", sa.String(500), nullable=False),
        sa.Column("change_ticket_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="eligible", nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_bounded_full_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "document_id", "attestation_number", name="uq_ai_bfp_doc_attempt"),
        sa.CheckConstraint("rollout_bucket BETWEEN 0 AND 99", name="ck_ai_bfp_doc_bucket"),
        sa.CheckConstraint("document_type IN ('chief_engineer_report','engine_log')", name="ck_ai_bfp_doc_type"),
        sa.CheckConstraint("confidentiality_level IN ('internal','confidential')", name="ck_ai_bfp_doc_conf"),
        sa.CheckConstraint("status IN ('eligible','revoked')", name="ck_ai_bfp_doc_status"),
    )
    op.create_index("ix_ai_bfp_doc_org", "ai_bounded_full_production_document_eligibility", ["organization_id", "authorization_id", "status"])

    op.create_table(
        "ai_bounded_full_production_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("eligibility_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("run_key", sa.String(120), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
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
        sa.Column("outcome_hash", sa.String(64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_bounded_full_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eligibility_id"], ["ai_bounded_full_production_document_eligibility.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processing_job_id"], ["document_processing_jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "run_key", name="uq_ai_bfp_run_key"),
        sa.UniqueConstraint("processing_job_id", name="uq_ai_bfp_processing_job"),
        sa.CheckConstraint("task_type IN ('chief_engineer_report','engine_log')", name="ck_ai_bfp_run_type"),
        sa.CheckConstraint("status IN ('queued','human_reviewed')", name="ck_ai_bfp_run_status"),
        sa.CheckConstraint("human_review_action IS NULL OR human_review_action IN ('approve','edit','reject')", name="ck_ai_bfp_run_action"),
    )
    op.create_index("ix_ai_bfp_run_org", "ai_bounded_full_production_runs", ["organization_id", "authorization_id", "status"])

    op.create_table(
        "ai_bounded_full_production_monitors",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("initiated_by_id", sa.Uuid(), nullable=True),
        sa.Column("monitor_key", sa.String(120), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("monitor_hash", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("monitored_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_bounded_full_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "monitor_key", name="uq_ai_bfp_monitor_key"),
        sa.CheckConstraint("status IN ('pass','fail')", name="ck_ai_bfp_monitor_status"),
    )
    op.create_index("ix_ai_bfp_monitor_org", "ai_bounded_full_production_monitors", ["organization_id", "authorization_id", "monitored_at"])

    op.create_table(
        "ai_bounded_full_production_incidents",
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
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_bounded_full_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_ai_bfp_incident_severity"),
        sa.CheckConstraint("category IN ('privacy','security','quality','cost','availability','cross_tenant','rollout','reliability','other')", name="ck_ai_bfp_incident_category"),
        sa.CheckConstraint("status IN ('open','resolved')", name="ck_ai_bfp_incident_status"),
    )
    op.create_index("ix_ai_bfp_incident_org", "ai_bounded_full_production_incidents", ["organization_id", "authorization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_ai_bfp_incident_org", table_name="ai_bounded_full_production_incidents")
    op.drop_table("ai_bounded_full_production_incidents")
    op.drop_index("ix_ai_bfp_monitor_org", table_name="ai_bounded_full_production_monitors")
    op.drop_table("ai_bounded_full_production_monitors")
    op.drop_index("ix_ai_bfp_run_org", table_name="ai_bounded_full_production_runs")
    op.drop_table("ai_bounded_full_production_runs")
    op.drop_index("ix_ai_bfp_doc_org", table_name="ai_bounded_full_production_document_eligibility")
    op.drop_table("ai_bounded_full_production_document_eligibility")
    op.drop_index("ix_ai_bfp_approval_org", table_name="ai_bounded_full_production_approvals")
    op.drop_table("ai_bounded_full_production_approvals")
    op.drop_index("ix_ai_bfp_near", table_name="ai_bounded_full_production_authorizations")
    op.drop_index("ix_ai_bfp_outcome", table_name="ai_bounded_full_production_authorizations")
    op.drop_index("ix_ai_bfp_org", table_name="ai_bounded_full_production_authorizations")
    op.drop_index("ix_ai_bfp_org_status", table_name="ai_bounded_full_production_authorizations")
    op.drop_table("ai_bounded_full_production_authorizations")
