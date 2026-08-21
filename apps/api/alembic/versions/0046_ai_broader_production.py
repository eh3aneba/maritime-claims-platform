"""separately authorized broader-production AI cohort

Revision ID: 0046_ai_broader_prod
Revises: 0045_ai_scale_outcome
"""
import sqlalchemy as sa
from alembic import op

revision = "0046_ai_broader_prod"
down_revision = "0045_ai_scale_outcome"
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
        "ai_broader_production_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("readiness_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("scale_up_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("authorization_key", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(30), server_default="production", nullable=False),
        sa.Column("authorization_mode", sa.String(60), server_default="broader_production_bounded", nullable=False),
        sa.Column("readiness_assessment_hash", sa.String(64), nullable=False),
        sa.Column("readiness_decision_hash", sa.String(64), nullable=False),
        sa.Column("scale_up_decision_hash", sa.String(64), nullable=False),
        sa.Column("inherited_outcome_assessment_hash", sa.String(64), nullable=False),
        sa.Column("inherited_outcome_decision_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("allowed_document_types", sa.JSON(), nullable=False),
        sa.Column("previous_rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("max_documents", sa.Integer(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_provider_runs", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rollback_slo_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("monitor_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="800", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("max_unsupported_output_rate_bps", sa.Integer(), server_default="75", nullable=False),
        sa.Column("min_source_grounding_validity_bps", sa.Integer(), server_default="9925", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="20000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(), server_default="500000", nullable=False),
        sa.Column("max_quality_regression_bps", sa.Integer(), server_default="300", nullable=False),
        sa.Column("max_latency_regression_bps", sa.Integer(), server_default="1500", nullable=False),
        sa.Column("max_cost_regression_bps", sa.Integer(), server_default="1500", nullable=False),
        sa.Column("deployment_isolation_reference", sa.String(500), nullable=False),
        sa.Column("provider_project_reference", sa.String(500), nullable=False),
        sa.Column("credential_control_reference", sa.String(500), nullable=False),
        sa.Column("privacy_legal_reference", sa.String(500), nullable=False),
        sa.Column("monitoring_reference", sa.String(500), nullable=False),
        sa.Column("incident_response_reference", sa.String(500), nullable=False),
        sa.Column("rollback_reference", sa.String(500), nullable=False),
        sa.Column("change_ticket_reference", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(60), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["readiness_assessment_id"], ["ai_scale_up_outcome_assessments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scale_up_authorization_id"], ["ai_scale_up_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "authorization_key", name="uq_ai_bp_org_key"),
        sa.UniqueConstraint("readiness_assessment_id", "attempt_number", name="uq_ai_bp_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_bp_attempt"),
        sa.CheckConstraint("previous_rollout_percentage BETWEEN 11 AND 25", name="ck_ai_bp_prev_rollout"),
        sa.CheckConstraint("rollout_percentage BETWEEN 26 AND 50", name="ck_ai_bp_rollout"),
        sa.CheckConstraint("max_reject_rate_bps = 800 AND max_edit_rate_bps = 3000", name="ck_ai_bp_review_rates"),
        sa.CheckConstraint("max_unsupported_output_rate_bps = 75 AND min_source_grounding_validity_bps = 9925", name="ck_ai_bp_grounding"),
        sa.CheckConstraint("max_p95_latency_ms = 20000 AND max_mean_cost_microusd = 500000", name="ck_ai_bp_ops"),
        sa.CheckConstraint("max_quality_regression_bps = 300 AND max_latency_regression_bps = 1500 AND max_cost_regression_bps = 1500", name="ck_ai_bp_trends"),
        sa.CheckConstraint("status IN ('pending_approvals','decision_ready','authorized','held','rejected','paused','revoked','completed','expired')", name="ck_ai_bp_status"),
    )
    op.create_index("ix_ai_bp_org", "ai_broader_production_authorizations", ["organization_id"])
    op.create_index("ix_ai_bp_ready", "ai_broader_production_authorizations", ["readiness_assessment_id"])
    op.create_index("ix_ai_bp_scale", "ai_broader_production_authorizations", ["scale_up_authorization_id"])
    op.create_index("ix_ai_bp_org_status", "ai_broader_production_authorizations", ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_broader_production_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(40), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_broader_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "approval_role", name="uq_ai_bp_approval_role"),
        sa.CheckConstraint("approval_role IN ('security','privacy','product','operations','risk','claims_governance')", name="ck_ai_bp_approval_role"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_ai_bp_approval_action"),
    )
    op.create_index("ix_ai_bp_approval_org", "ai_broader_production_approvals", ["organization_id", "authorization_id"])

    op.create_table(
        "ai_broader_production_document_eligibility",
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
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_broader_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "document_id", "attestation_number", name="uq_ai_bp_doc_attempt"),
        sa.CheckConstraint("attestation_number >= 1", name="ck_ai_bp_doc_attempt"),
        sa.CheckConstraint("rollout_bucket BETWEEN 0 AND 99", name="ck_ai_bp_doc_bucket"),
        sa.CheckConstraint("document_type IN ('chief_engineer_report','engine_log')", name="ck_ai_bp_doc_type"),
        sa.CheckConstraint("confidentiality_level IN ('internal','confidential')", name="ck_ai_bp_doc_conf"),
        sa.CheckConstraint("status IN ('eligible','revoked')", name="ck_ai_bp_doc_status"),
    )
    op.create_index("ix_ai_bp_doc_org", "ai_broader_production_document_eligibility", ["organization_id", "authorization_id", "status"])
    op.create_index("ix_ai_bp_doc_id", "ai_broader_production_document_eligibility", ["document_id"])

    op.create_table(
        "ai_broader_production_runs",
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
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_broader_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eligibility_id"], ["ai_broader_production_document_eligibility.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processing_job_id"], ["document_processing_jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "run_key", name="uq_ai_bp_run_key"),
        sa.UniqueConstraint("processing_job_id", name="uq_ai_bp_processing_job"),
        sa.CheckConstraint("status IN ('queued','human_reviewed')", name="ck_ai_bp_run_status"),
        sa.CheckConstraint("human_review_action IS NULL OR human_review_action IN ('approve','edit','reject')", name="ck_ai_bp_run_action"),
    )
    op.create_index("ix_ai_bp_run_org", "ai_broader_production_runs", ["organization_id", "authorization_id", "status"])

    op.create_table(
        "ai_broader_production_monitors",
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
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_broader_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "monitor_key", name="uq_ai_bp_monitor_key"),
        sa.CheckConstraint("status IN ('pass','rollback_required')", name="ck_ai_bp_monitor_status"),
    )
    op.create_index("ix_ai_bp_monitor_org", "ai_broader_production_monitors", ["organization_id", "authorization_id", "monitored_at"])

    op.create_table(
        "ai_broader_production_incidents",
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
        sa.ForeignKeyConstraint(["authorization_id"], ["ai_broader_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_ai_bp_incident_severity"),
        sa.CheckConstraint("category IN ('privacy','security','quality','cost','availability','cross_tenant','rollout','other')", name="ck_ai_bp_incident_category"),
        sa.CheckConstraint("status IN ('open','resolved')", name="ck_ai_bp_incident_status"),
    )
    op.create_index("ix_ai_bp_incident_org", "ai_broader_production_incidents", ["organization_id", "authorization_id", "status"])


def downgrade() -> None:
    op.drop_table("ai_broader_production_incidents")
    op.drop_table("ai_broader_production_monitors")
    op.drop_table("ai_broader_production_runs")
    op.drop_table("ai_broader_production_document_eligibility")
    op.drop_table("ai_broader_production_approvals")
    op.drop_table("ai_broader_production_authorizations")
