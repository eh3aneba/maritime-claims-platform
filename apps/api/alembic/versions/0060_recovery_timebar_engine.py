"""Recovery and time-bar intelligence foundation

Revision ID: 0060_recovery_timebar_engine
Revises: 0059_marine_rule_dispositions
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_recovery_timebar_engine"
down_revision = "0059_marine_rule_dispositions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_timebar_snapshots",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("generated_by_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.String(30), nullable=False),
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("source_state_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "snapshot_version", name="uq_recovery_timebar_snapshot_version"),
        sa.UniqueConstraint("organization_id", "claim_id", "source_state_hash", name="uq_recovery_timebar_source_state"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_recovery_timebar_snapshot_version"),
    )
    op.create_index("ix_recovery_timebar_snapshot_claim", "recovery_timebar_snapshots", ["organization_id", "claim_id", "snapshot_version"])
    op.create_index("ix_recovery_timebar_snapshots_organization_id", "recovery_timebar_snapshots", ["organization_id"])
    op.create_index("ix_recovery_timebar_snapshots_claim_id", "recovery_timebar_snapshots", ["claim_id"])

    op.create_table(
        "recovery_timebar_evaluations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("counterparty", sa.String(240), nullable=True),
        sa.Column("candidate_basis", sa.Text(), nullable=True),
        sa.Column("trigger_date", sa.Date(), nullable=True),
        sa.Column("period_value", sa.Integer(), nullable=True),
        sa.Column("period_unit", sa.String(16), nullable=True),
        sa.Column("candidate_deadline", sa.Date(), nullable=True),
        sa.Column("days_remaining", sa.Integer(), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("candidate_implication", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("missing_prerequisites", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("evaluation_hash", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["recovery_timebar_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "evaluation_key", name="uq_recovery_timebar_eval_key"),
        sa.CheckConstraint("kind IN ('recovery','timebar')", name="ck_recovery_timebar_eval_kind"),
        sa.CheckConstraint("status IN ('triggered','not_triggered','insufficient_evidence','not_applicable')", name="ck_recovery_timebar_eval_status"),
        sa.CheckConstraint("urgency IN ('low','medium','high','critical')", name="ck_recovery_timebar_eval_urgency"),
        sa.CheckConstraint("period_value IS NULL OR period_value > 0", name="ck_recovery_timebar_period_value"),
        sa.CheckConstraint("period_unit IS NULL OR period_unit IN ('days','months','years')", name="ck_recovery_timebar_period_unit"),
    )
    op.create_index("ix_recovery_timebar_eval_claim", "recovery_timebar_evaluations", ["organization_id", "claim_id", "kind", "status"])
    op.create_index("ix_recovery_timebar_evaluations_organization_id", "recovery_timebar_evaluations", ["organization_id"])
    op.create_index("ix_recovery_timebar_evaluations_claim_id", "recovery_timebar_evaluations", ["claim_id"])
    op.create_index("ix_recovery_timebar_evaluations_snapshot_id", "recovery_timebar_evaluations", ["snapshot_id"])

    op.create_table(
        "recovery_timebar_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("converted_task_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_hash", sa.String(64), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("edited_candidate_implication", sa.Text(), nullable=True),
        sa.Column("edited_recommended_action", sa.Text(), nullable=True),
        sa.Column("edited_due_date", sa.Date(), nullable=True),
        sa.Column("previous_decision_hash", sa.String(64), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["recovery_timebar_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_id"], ["recovery_timebar_evaluations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["converted_task_id"], ["claim_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_id", "decision_number", name="uq_recovery_timebar_decision_number"),
        sa.CheckConstraint("decision_number >= 1", name="ck_recovery_timebar_decision_number"),
        sa.CheckConstraint("action IN ('accept','edit','dismiss','not_applicable')", name="ck_recovery_timebar_decision_action"),
    )
    op.create_index("ix_recovery_timebar_decision_eval", "recovery_timebar_decisions", ["organization_id", "claim_id", "evaluation_id", "decision_number"])
    op.create_index("ix_recovery_timebar_decisions_organization_id", "recovery_timebar_decisions", ["organization_id"])
    op.create_index("ix_recovery_timebar_decisions_claim_id", "recovery_timebar_decisions", ["claim_id"])
    op.create_index("ix_recovery_timebar_decisions_snapshot_id", "recovery_timebar_decisions", ["snapshot_id"])
    op.create_index("ix_recovery_timebar_decisions_evaluation_id", "recovery_timebar_decisions", ["evaluation_id"])


def downgrade() -> None:
    op.drop_index("ix_recovery_timebar_decisions_evaluation_id", table_name="recovery_timebar_decisions")
    op.drop_index("ix_recovery_timebar_decisions_snapshot_id", table_name="recovery_timebar_decisions")
    op.drop_index("ix_recovery_timebar_decisions_claim_id", table_name="recovery_timebar_decisions")
    op.drop_index("ix_recovery_timebar_decisions_organization_id", table_name="recovery_timebar_decisions")
    op.drop_index("ix_recovery_timebar_decision_eval", table_name="recovery_timebar_decisions")
    op.drop_table("recovery_timebar_decisions")
    op.drop_index("ix_recovery_timebar_evaluations_snapshot_id", table_name="recovery_timebar_evaluations")
    op.drop_index("ix_recovery_timebar_evaluations_claim_id", table_name="recovery_timebar_evaluations")
    op.drop_index("ix_recovery_timebar_evaluations_organization_id", table_name="recovery_timebar_evaluations")
    op.drop_index("ix_recovery_timebar_eval_claim", table_name="recovery_timebar_evaluations")
    op.drop_table("recovery_timebar_evaluations")
    op.drop_index("ix_recovery_timebar_snapshots_claim_id", table_name="recovery_timebar_snapshots")
    op.drop_index("ix_recovery_timebar_snapshots_organization_id", table_name="recovery_timebar_snapshots")
    op.drop_index("ix_recovery_timebar_snapshot_claim", table_name="recovery_timebar_snapshots")
    op.drop_table("recovery_timebar_snapshots")
