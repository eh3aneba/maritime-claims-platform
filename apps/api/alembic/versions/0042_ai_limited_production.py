"""separately authorized limited-production AI evaluation

Revision ID: 0042_ai_limited_production
Revises: 0041_ai_pilot_outcomes
"""
import sqlalchemy as sa
from alembic import op

revision = "0042_ai_limited_production"
down_revision = "0041_ai_pilot_outcomes"
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
        "ai_limited_production_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_suite_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("authorization_key", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(30), server_default="production", nullable=False),
        sa.Column("evaluation_mode", sa.String(50),
                  server_default="limited_production_evaluation", nullable=False),
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
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rollback_slo_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("monitor_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("max_reject_rate_bps", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("max_edit_rate_bps", sa.Integer(), server_default="5000", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="30000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(),
                  server_default="500000", nullable=False),
        sa.Column("deployment_isolation_reference", sa.String(500), nullable=False),
        sa.Column("provider_project_reference", sa.String(500), nullable=False),
        sa.Column("credential_control_reference", sa.String(500), nullable=False),
        sa.Column("data_processing_reference", sa.String(500), nullable=False),
        sa.Column("monitoring_reference", sa.String(500), nullable=False),
        sa.Column("rollback_reference", sa.String(500), nullable=False),
        sa.Column("change_ticket_reference", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outcome_assessment_id"],
                                ["ai_pilot_outcome_assessments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pilot_id"],
                                ["ai_private_pilot_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evaluation_suite_id"],
                                ["ai_evaluation_suites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "authorization_key",
                            name="uq_ai_limited_production_org_key"),
        sa.UniqueConstraint("outcome_assessment_id", "attempt_number",
                            name="uq_ai_limited_production_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_limited_production_attempt"),
        sa.CheckConstraint("environment = 'production' AND "
                           "evaluation_mode = 'limited_production_evaluation'",
                           name="ck_ai_limited_production_mode"),
        sa.CheckConstraint("rollout_percentage BETWEEN 1 AND 10",
                           name="ck_ai_limited_production_rollout"),
        sa.CheckConstraint("max_claims BETWEEN 1 AND 10 AND max_documents BETWEEN 1 AND 30 "
                           "AND max_users BETWEEN 1 AND 10 AND max_provider_runs BETWEEN 1 AND 100",
                           name="ck_ai_limited_production_caps"),
        sa.CheckConstraint("max_documents >= max_claims",
                           name="ck_ai_limited_production_cap_order"),
        sa.CheckConstraint("expires_at > starts_at",
                           name="ck_ai_limited_production_window"),
        sa.CheckConstraint("rollback_slo_minutes = 15 AND monitor_interval_minutes = 60",
                           name="ck_ai_limited_production_slos"),
        sa.CheckConstraint("max_reject_rate_bps = 2000 AND max_edit_rate_bps = 5000 "
                           "AND max_p95_latency_ms = 30000 "
                           "AND max_mean_cost_microusd = 500000",
                           name="ck_ai_limited_production_thresholds"),
        sa.CheckConstraint(
            "status IN ('pending_approvals', 'decision_ready', 'authorized', 'held', "
            "'rejected', 'paused', 'revoked', 'completed')",
            name="ck_ai_limited_production_status"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('authorize_limited_evaluation', 'hold', "
            "'rejected', 'monitor_rollback_required', 'incident_rollback', "
            "'resumed_after_monitor', 'revoked', 'completed')",
            name="ck_ai_limited_production_outcome"),
    )
    for column in ("organization_id", "outcome_assessment_id", "pilot_id", "evaluation_suite_id"):
        op.create_index(f"ix_ai_limited_production_authorizations_{column}",
                        "ai_limited_production_authorizations", [column])
    op.create_index("ix_ai_limited_production_org_status",
                    "ai_limited_production_authorizations",
                    ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_limited_production_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"],
                                ["ai_limited_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "approval_role",
                            name="uq_ai_limited_production_approval_role"),
        sa.CheckConstraint("approval_role IN ('security', 'privacy', 'product', 'operations')",
                           name="ck_ai_limited_production_approval_role"),
        sa.CheckConstraint("action IN ('approve', 'reject')",
                           name="ck_ai_limited_production_approval_action"),
    )
    op.create_index("ix_ai_limited_production_approvals_organization_id",
                    "ai_limited_production_approvals", ["organization_id"])
    op.create_index("ix_ai_limited_production_approvals_authorization_id",
                    "ai_limited_production_approvals", ["authorization_id"])
    op.create_index("ix_ai_limited_production_approval_org",
                    "ai_limited_production_approvals", ["organization_id", "authorization_id"])

    op.create_table(
        "ai_limited_production_document_eligibility",
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
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"],
                                ["ai_limited_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "document_id", "attestation_number",
                            name="uq_ai_limited_production_document_attempt"),
        sa.CheckConstraint("attestation_number >= 1",
                           name="ck_ai_limited_production_document_attempt"),
        sa.CheckConstraint("rollout_bucket BETWEEN 0 AND 99",
                           name="ck_ai_limited_production_document_bucket"),
        sa.CheckConstraint("document_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_limited_production_document_type"),
        sa.CheckConstraint("confidentiality_level <> 'restricted'",
                           name="ck_ai_limited_production_no_restricted"),
        sa.CheckConstraint("status IN ('eligible', 'revoked')",
                           name="ck_ai_limited_production_document_status"),
    )
    for column in ("organization_id", "authorization_id", "claim_id", "document_id"):
        op.create_index(f"ix_ai_limited_production_document_{column}",
                        "ai_limited_production_document_eligibility", [column])
    op.create_index("ix_ai_limited_production_document_org",
                    "ai_limited_production_document_eligibility",
                    ["organization_id", "authorization_id", "status"])

    op.create_table(
        "ai_limited_production_runs",
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
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("observed_provider_cost_microusd", sa.Integer(), nullable=True),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("outcome_hash", sa.String(64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"],
                                ["ai_limited_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eligibility_id"],
                                ["ai_limited_production_document_eligibility.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processing_job_id"],
                                ["document_processing_jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "run_key",
                            name="uq_ai_limited_production_run_key"),
        sa.UniqueConstraint("processing_job_id",
                            name="uq_ai_limited_production_processing_job"),
        sa.CheckConstraint("task_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_limited_production_run_type"),
        sa.CheckConstraint("status IN ('queued', 'human_reviewed')",
                           name="ck_ai_limited_production_run_status"),
        sa.CheckConstraint(
            "human_review_action IS NULL OR human_review_action IN ('approve', 'edit', 'reject')",
            name="ck_ai_limited_production_run_review"),
        sa.CheckConstraint(
            "output_candidate_count IS NULL OR output_candidate_count >= 0",
            name="ck_ai_limited_production_run_candidates"),
        sa.CheckConstraint(
            "human_edit_count IS NULL OR human_edit_count >= 0",
            name="ck_ai_limited_production_run_edits"),
        sa.CheckConstraint(
            "human_edit_count IS NULL OR output_candidate_count IS NULL "
            "OR human_edit_count <= output_candidate_count",
            name="ck_ai_limited_production_run_edit_limit"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms > 0",
                           name="ck_ai_limited_production_run_latency"),
        sa.CheckConstraint(
            "observed_provider_cost_microusd IS NULL "
            "OR observed_provider_cost_microusd >= 0",
            name="ck_ai_limited_production_run_cost"),
    )
    for column in ("organization_id", "authorization_id", "eligibility_id",
                   "claim_id", "document_id", "processing_job_id"):
        op.create_index(f"ix_ai_limited_production_runs_{column}",
                        "ai_limited_production_runs", [column])
    op.create_index("ix_ai_limited_production_run_org", "ai_limited_production_runs",
                    ["organization_id", "authorization_id", "status"])

    op.create_table(
        "ai_limited_production_monitors",
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
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"],
                                ["ai_limited_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "monitor_key",
                            name="uq_ai_limited_production_monitor_key"),
        sa.CheckConstraint("status IN ('pass', 'rollback_required')",
                           name="ck_ai_limited_production_monitor_status"),
    )
    op.create_index("ix_ai_limited_production_monitors_organization_id",
                    "ai_limited_production_monitors", ["organization_id"])
    op.create_index("ix_ai_limited_production_monitors_authorization_id",
                    "ai_limited_production_monitors", ["authorization_id"])
    op.create_index("ix_ai_limited_production_monitor_org",
                    "ai_limited_production_monitors",
                    ["organization_id", "authorization_id", "monitored_at"])

    op.create_table(
        "ai_limited_production_incidents",
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
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"],
                                ["ai_limited_production_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')",
                           name="ck_ai_limited_production_incident_severity"),
        sa.CheckConstraint("category IN ('privacy', 'security', 'quality', 'cost', "
                           "'availability', 'cross_tenant', 'rollout', 'other')",
                           name="ck_ai_limited_production_incident_category"),
        sa.CheckConstraint("status IN ('open', 'resolved')",
                           name="ck_ai_limited_production_incident_status"),
    )
    op.create_index("ix_ai_limited_production_incidents_organization_id",
                    "ai_limited_production_incidents", ["organization_id"])
    op.create_index("ix_ai_limited_production_incidents_authorization_id",
                    "ai_limited_production_incidents", ["authorization_id"])
    op.create_index("ix_ai_limited_production_incident_org",
                    "ai_limited_production_incidents",
                    ["organization_id", "authorization_id", "status"])


def downgrade() -> None:
    op.drop_table("ai_limited_production_incidents")
    op.drop_table("ai_limited_production_monitors")
    op.drop_table("ai_limited_production_runs")
    op.drop_table("ai_limited_production_document_eligibility")
    op.drop_table("ai_limited_production_approvals")
    op.drop_table("ai_limited_production_authorizations")
