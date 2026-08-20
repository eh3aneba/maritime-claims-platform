"""private pilot execution and production architecture baseline

Revision ID: 0034_pilot_architecture
Revises: 0033_partner_rehearsal
"""
import sqlalchemy as sa
from alembic import op

revision = "0034_pilot_architecture"
down_revision = "0033_partner_rehearsal"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "private_pilot_executions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("completed_by_id", sa.Uuid(), nullable=True),
        sa.Column("execution_key", sa.String(120), nullable=False),
        sa.Column("design_partner_label", sa.String(200), nullable=False),
        sa.Column("data_mode", sa.String(30), nullable=False),
        sa.Column("data_authorization_reference", sa.String(500), nullable=True),
        sa.Column("objectives", sa.JSON(), nullable=False),
        sa.Column("target_case_runs", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), server_default="draft", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("outcome_hash", sa.String(64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rehearsal_id"], ["design_partner_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "execution_key", name="uq_private_pilot_execution_key"),
        sa.UniqueConstraint("rehearsal_id", name="uq_private_pilot_execution_rehearsal"),
        sa.CheckConstraint("target_case_runs >= 1 AND target_case_runs <= 50", name="ck_private_pilot_target_cases"),
    )
    op.create_index("ix_private_pilot_executions_organization_id", "private_pilot_executions", ["organization_id"])
    op.create_index("ix_private_pilot_executions_rehearsal_id", "private_pilot_executions", ["rehearsal_id"])
    op.create_index("ix_private_pilot_execution_org_status", "private_pilot_executions", ["organization_id", "status", "created_at"])

    op.create_table(
        "private_pilot_case_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("case_outcome", sa.String(30), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("triage_minutes", sa.Integer(), nullable=True),
        sa.Column("evidence_review_minutes", sa.Integer(), nullable=True),
        sa.Column("assessment_minutes", sa.Integer(), nullable=True),
        sa.Column("adjustment_minutes", sa.Integer(), nullable=True),
        sa.Column("ai_candidates_reviewed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_accepted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_edited", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_rejected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rule_findings_reviewed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rule_findings_helpful", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_conflicts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_requirements", sa.Integer(), server_default="0", nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["private_pilot_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "claim_id", name="uq_private_pilot_case_claim"),
        sa.CheckConstraint(
            "ai_candidates_reviewed >= 0 AND ai_accepted >= 0 AND ai_edited >= 0 AND ai_rejected >= 0 "
            "AND rule_findings_reviewed >= 0 AND rule_findings_helpful >= 0 "
            "AND open_conflicts >= 0 AND open_requirements >= 0",
            name="ck_private_pilot_case_counts_nonnegative",
        ),
    )
    op.create_index("ix_private_pilot_case_runs_organization_id", "private_pilot_case_runs", ["organization_id"])
    op.create_index("ix_private_pilot_case_runs_execution_id", "private_pilot_case_runs", ["execution_id"])
    op.create_index("ix_private_pilot_case_runs_claim_id", "private_pilot_case_runs", ["claim_id"])
    op.create_index("ix_private_pilot_case_org_execution", "private_pilot_case_runs", ["organization_id", "execution_id", "recorded_at"])

    op.create_table(
        "product_gap_findings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("case_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("owner_label", sa.String(180), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), server_default="open", nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["private_pilot_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_run_id"], ["private_pilot_case_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_gap_findings_organization_id", "product_gap_findings", ["organization_id"])
    op.create_index("ix_product_gap_findings_execution_id", "product_gap_findings", ["execution_id"])
    op.create_index("ix_product_gap_org_execution_status", "product_gap_findings", ["organization_id", "execution_id", "status"])

    op.create_table(
        "production_architecture_baselines",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_execution_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("attested_by_id", sa.Uuid(), nullable=True),
        sa.Column("baseline_key", sa.String(120), nullable=False),
        sa.Column("deployment_model", sa.String(40), nullable=False),
        sa.Column("data_residency_region", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), server_default="draft", nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=True),
        sa.Column("attestation_note", sa.Text(), nullable=True),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pilot_execution_id"], ["private_pilot_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "baseline_key", name="uq_production_architecture_baseline_key"),
    )
    op.create_index("ix_production_architecture_baselines_organization_id", "production_architecture_baselines", ["organization_id"])
    op.create_index("ix_production_architecture_baselines_pilot_execution_id", "production_architecture_baselines", ["pilot_execution_id"])
    op.create_index("ix_production_architecture_org_status", "production_architecture_baselines", ["organization_id", "status", "created_at"])

    op.create_table(
        "production_architecture_controls",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("control_key", sa.String(50), nullable=False),
        sa.Column("current_state", sa.String(30), nullable=False),
        sa.Column("target_architecture", sa.Text(), nullable=False),
        sa.Column("risk_note", sa.Text(), nullable=False),
        sa.Column("owner_label", sa.String(180), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["baseline_id"], ["production_architecture_baselines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("baseline_id", "control_key", name="uq_production_architecture_control"),
    )
    op.create_index("ix_production_architecture_controls_organization_id", "production_architecture_controls", ["organization_id"])
    op.create_index("ix_production_architecture_controls_baseline_id", "production_architecture_controls", ["baseline_id"])
    op.create_index("ix_production_architecture_control_org", "production_architecture_controls", ["organization_id", "baseline_id", "current_state"])


def downgrade() -> None:
    for table, indexes in [
        ("production_architecture_controls", ["ix_production_architecture_control_org", "ix_production_architecture_controls_baseline_id", "ix_production_architecture_controls_organization_id"]),
        ("production_architecture_baselines", ["ix_production_architecture_org_status", "ix_production_architecture_baselines_pilot_execution_id", "ix_production_architecture_baselines_organization_id"]),
        ("product_gap_findings", ["ix_product_gap_org_execution_status", "ix_product_gap_findings_execution_id", "ix_product_gap_findings_organization_id"]),
        ("private_pilot_case_runs", ["ix_private_pilot_case_org_execution", "ix_private_pilot_case_runs_claim_id", "ix_private_pilot_case_runs_execution_id", "ix_private_pilot_case_runs_organization_id"]),
        ("private_pilot_executions", ["ix_private_pilot_execution_org_status", "ix_private_pilot_executions_rehearsal_id", "ix_private_pilot_executions_organization_id"]),
    ]:
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
