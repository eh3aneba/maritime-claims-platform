"""bounded real-document private AI pilot

Revision ID: 0040_ai_private_pilot
Revises: 0039_ai_evaluation
"""
import sqlalchemy as sa
from alembic import op

revision = "0040_ai_private_pilot"
down_revision = "0039_ai_evaluation"
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
        "ai_private_pilot_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("activation_request_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_suite_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("pilot_key", sa.String(120), nullable=False),
        sa.Column("data_mode", sa.String(40), server_default="real_non_restricted", nullable=False),
        sa.Column("allowed_document_types", sa.JSON(), nullable=False),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("max_documents", sa.Integer(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_provider_runs", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_authorization_reference", sa.String(500), nullable=False),
        sa.Column("data_owner_authorization_reference", sa.String(500), nullable=False),
        sa.Column("monitoring_reference", sa.String(500), nullable=False),
        sa.Column("incident_runbook_reference", sa.String(500), nullable=False),
        sa.Column("rollback_reference", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_request_id"],
                                ["ai_provider_activation_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evaluation_suite_id"],
                                ["ai_evaluation_suites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "pilot_key", name="uq_ai_private_pilot_org_key"),
        sa.UniqueConstraint("organization_id", "attempt_number", name="uq_ai_private_pilot_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_private_pilot_attempt"),
        sa.CheckConstraint("data_mode = 'real_non_restricted'", name="ck_ai_private_pilot_data_mode"),
        sa.CheckConstraint("max_claims BETWEEN 1 AND 20 AND max_documents BETWEEN 1 AND 100 "
                           "AND max_users BETWEEN 1 AND 50 AND max_provider_runs BETWEEN 1 AND 500",
                           name="ck_ai_private_pilot_caps"),
        sa.CheckConstraint("max_documents >= max_claims", name="ck_ai_private_pilot_cap_order"),
        sa.CheckConstraint("expires_at > starts_at", name="ck_ai_private_pilot_window"),
    )
    op.create_index("ix_ai_private_pilot_authorizations_organization_id",
                    "ai_private_pilot_authorizations", ["organization_id"])
    op.create_index("ix_ai_private_pilot_authorizations_activation_id",
                    "ai_private_pilot_authorizations", ["activation_request_id"])
    op.create_index("ix_ai_private_pilot_authorizations_evaluation_id",
                    "ai_private_pilot_authorizations", ["evaluation_suite_id"])
    op.create_index("ix_ai_private_pilot_org_status", "ai_private_pilot_authorizations",
                    ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_private_pilot_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pilot_id"], ["ai_private_pilot_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_id", "approval_role", name="uq_ai_private_pilot_approval_role"),
        sa.CheckConstraint("approval_role IN ('organization_owner', 'data_owner')",
                           name="ck_ai_private_pilot_approval_role"),
        sa.CheckConstraint("action IN ('approve', 'reject')",
                           name="ck_ai_private_pilot_approval_action"),
    )
    op.create_index("ix_ai_private_pilot_approvals_organization_id",
                    "ai_private_pilot_approvals", ["organization_id"])
    op.create_index("ix_ai_private_pilot_approvals_pilot_id",
                    "ai_private_pilot_approvals", ["pilot_id"])
    op.create_index("ix_ai_private_pilot_approval_org", "ai_private_pilot_approvals",
                    ["organization_id", "pilot_id"])

    op.create_table(
        "ai_private_pilot_document_eligibility",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attested_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attestation_number", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("confidentiality_level", sa.String(30), nullable=False),
        sa.Column("authorization_basis", sa.String(50), nullable=False),
        sa.Column("authorization_reference", sa.String(500), nullable=False),
        sa.Column("data_minimization_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="eligible", nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pilot_id"], ["ai_private_pilot_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_id", "document_id", "attestation_number",
                            name="uq_ai_private_pilot_document_attempt"),
        sa.CheckConstraint("attestation_number >= 1", name="ck_ai_pilot_document_attempt"),
        sa.CheckConstraint("document_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_pilot_document_type"),
        sa.CheckConstraint("confidentiality_level <> 'restricted'",
                           name="ck_ai_pilot_document_no_restricted"),
        sa.CheckConstraint("authorization_basis IN ('organization_and_data_owner', "
                           "'explicit_data_owner_consent')",
                           name="ck_ai_pilot_document_basis"),
    )
    op.create_index("ix_ai_pilot_document_organization_id",
                    "ai_private_pilot_document_eligibility", ["organization_id"])
    op.create_index("ix_ai_pilot_document_pilot_id",
                    "ai_private_pilot_document_eligibility", ["pilot_id"])
    op.create_index("ix_ai_pilot_document_claim_id",
                    "ai_private_pilot_document_eligibility", ["claim_id"])
    op.create_index("ix_ai_pilot_document_document_id",
                    "ai_private_pilot_document_eligibility", ["document_id"])
    op.create_index("ix_ai_private_pilot_document_org",
                    "ai_private_pilot_document_eligibility", ["organization_id", "pilot_id", "status"])

    op.create_table(
        "ai_private_pilot_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["pilot_id"], ["ai_private_pilot_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eligibility_id"],
                                ["ai_private_pilot_document_eligibility.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processing_job_id"],
                                ["document_processing_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_id", "run_key", name="uq_ai_private_pilot_run_key"),
        sa.UniqueConstraint("processing_job_id", name="uq_ai_private_pilot_processing_job"),
        sa.CheckConstraint("task_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_private_pilot_run_task"),
        sa.CheckConstraint("status IN ('queued', 'human_reviewed')",
                           name="ck_ai_private_pilot_run_status"),
        sa.CheckConstraint("human_review_action IS NULL OR human_review_action IN "
                           "('approve', 'edit', 'reject')", name="ck_ai_private_pilot_run_review"),
        sa.CheckConstraint("output_candidate_count IS NULL OR output_candidate_count >= 0",
                           name="ck_ai_private_pilot_run_candidates"),
        sa.CheckConstraint("human_edit_count IS NULL OR human_edit_count >= 0",
                           name="ck_ai_private_pilot_run_edits"),
    )
    op.create_index("ix_ai_private_pilot_runs_organization_id",
                    "ai_private_pilot_runs", ["organization_id"])
    op.create_index("ix_ai_private_pilot_runs_pilot_id", "ai_private_pilot_runs", ["pilot_id"])
    op.create_index("ix_ai_private_pilot_runs_eligibility_id",
                    "ai_private_pilot_runs", ["eligibility_id"])
    op.create_index("ix_ai_private_pilot_runs_processing_job_id",
                    "ai_private_pilot_runs", ["processing_job_id"])
    op.create_index("ix_ai_private_pilot_run_org", "ai_private_pilot_runs",
                    ["organization_id", "pilot_id", "status"])

    op.create_table(
        "ai_private_pilot_incidents",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["pilot_id"], ["ai_private_pilot_authorizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')",
                           name="ck_ai_private_pilot_incident_severity"),
        sa.CheckConstraint("category IN ('privacy', 'security', 'quality', 'cost', "
                           "'availability', 'cross_tenant', 'other')",
                           name="ck_ai_private_pilot_incident_category"),
        sa.CheckConstraint("status IN ('open', 'resolved')",
                           name="ck_ai_private_pilot_incident_status"),
    )
    op.create_index("ix_ai_private_pilot_incidents_organization_id",
                    "ai_private_pilot_incidents", ["organization_id"])
    op.create_index("ix_ai_private_pilot_incidents_pilot_id",
                    "ai_private_pilot_incidents", ["pilot_id"])
    op.create_index("ix_ai_private_pilot_incident_org", "ai_private_pilot_incidents",
                    ["organization_id", "pilot_id", "status"])


def downgrade() -> None:
    op.drop_table("ai_private_pilot_incidents")
    op.drop_table("ai_private_pilot_runs")
    op.drop_table("ai_private_pilot_document_eligibility")
    op.drop_table("ai_private_pilot_approvals")
    op.drop_table("ai_private_pilot_authorizations")
