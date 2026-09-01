"""Severity and reserve support engine

Revision ID: 0061_severity_reserve_support
Revises: 0060_recovery_timebar_engine
"""
import sqlalchemy as sa
from alembic import op

revision = "0061_severity_reserve_support"
down_revision = "0060_recovery_timebar_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "severity_reserve_snapshots",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("generated_by_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.String(30), nullable=False),
        sa.Column("source_state_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "snapshot_version", name="uq_severity_reserve_snapshot_version"),
        sa.UniqueConstraint("organization_id", "claim_id", "source_state_hash", name="uq_severity_reserve_source_state"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_severity_reserve_snapshot_version"),
    )
    op.create_index("ix_severity_reserve_snapshot_claim", "severity_reserve_snapshots", ["organization_id", "claim_id", "snapshot_version"])
    op.create_index("ix_severity_reserve_snapshots_organization_id", "severity_reserve_snapshots", ["organization_id"])
    op.create_index("ix_severity_reserve_snapshots_claim_id", "severity_reserve_snapshots", ["claim_id"])

    op.create_table(
        "severity_reserve_evaluations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("severity_label", sa.String(16), nullable=True),
        sa.Column("severity_score", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("lower_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("upper_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("candidate_implication", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("missing_prerequisites", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("evaluation_hash", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["severity_reserve_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "evaluation_key", name="uq_severity_reserve_eval_key"),
        sa.CheckConstraint("kind IN ('severity','reserve')", name="ck_severity_reserve_eval_kind"),
        sa.CheckConstraint("status IN ('triggered','not_triggered','insufficient_evidence','not_applicable')", name="ck_severity_reserve_eval_status"),
        sa.CheckConstraint("severity_label IS NULL OR severity_label IN ('low','medium','high','critical')", name="ck_severity_reserve_label"),
        sa.CheckConstraint("severity_score IS NULL OR severity_score >= 0", name="ck_severity_reserve_score"),
        sa.CheckConstraint("lower_amount IS NULL OR lower_amount >= 0", name="ck_severity_reserve_lower_nonnegative"),
        sa.CheckConstraint("upper_amount IS NULL OR upper_amount >= 0", name="ck_severity_reserve_upper_nonnegative"),
        sa.CheckConstraint("lower_amount IS NULL OR upper_amount IS NULL OR lower_amount <= upper_amount", name="ck_severity_reserve_range_order"),
    )
    op.create_index("ix_severity_reserve_eval_claim", "severity_reserve_evaluations", ["organization_id", "claim_id", "kind", "status"])
    op.create_index("ix_severity_reserve_evaluations_organization_id", "severity_reserve_evaluations", ["organization_id"])
    op.create_index("ix_severity_reserve_evaluations_claim_id", "severity_reserve_evaluations", ["claim_id"])
    op.create_index("ix_severity_reserve_evaluations_snapshot_id", "severity_reserve_evaluations", ["snapshot_id"])

    op.create_table(
        "severity_reserve_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_hash", sa.String(64), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("edited_severity_label", sa.String(16), nullable=True),
        sa.Column("edited_lower_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("edited_upper_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("previous_decision_hash", sa.String(64), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["severity_reserve_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_id"], ["severity_reserve_evaluations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_id", "decision_number", name="uq_severity_reserve_decision_number"),
        sa.CheckConstraint("decision_number >= 1", name="ck_severity_reserve_decision_number"),
        sa.CheckConstraint("action IN ('accept','edit','dismiss','not_applicable')", name="ck_severity_reserve_decision_action"),
        sa.CheckConstraint("edited_severity_label IS NULL OR edited_severity_label IN ('low','medium','high','critical')", name="ck_severity_reserve_decision_label"),
        sa.CheckConstraint("edited_lower_amount IS NULL OR edited_lower_amount >= 0", name="ck_severity_reserve_decision_lower"),
        sa.CheckConstraint("edited_upper_amount IS NULL OR edited_upper_amount >= 0", name="ck_severity_reserve_decision_upper"),
        sa.CheckConstraint("edited_lower_amount IS NULL OR edited_upper_amount IS NULL OR edited_lower_amount <= edited_upper_amount", name="ck_severity_reserve_decision_range_order"),
    )
    op.create_index("ix_severity_reserve_decision_eval", "severity_reserve_decisions", ["organization_id", "claim_id", "evaluation_id", "decision_number"])
    op.create_index("ix_severity_reserve_decisions_organization_id", "severity_reserve_decisions", ["organization_id"])
    op.create_index("ix_severity_reserve_decisions_claim_id", "severity_reserve_decisions", ["claim_id"])
    op.create_index("ix_severity_reserve_decisions_snapshot_id", "severity_reserve_decisions", ["snapshot_id"])
    op.create_index("ix_severity_reserve_decisions_evaluation_id", "severity_reserve_decisions", ["evaluation_id"])


def downgrade() -> None:
    op.drop_index("ix_severity_reserve_decisions_evaluation_id", table_name="severity_reserve_decisions")
    op.drop_index("ix_severity_reserve_decisions_snapshot_id", table_name="severity_reserve_decisions")
    op.drop_index("ix_severity_reserve_decisions_claim_id", table_name="severity_reserve_decisions")
    op.drop_index("ix_severity_reserve_decisions_organization_id", table_name="severity_reserve_decisions")
    op.drop_index("ix_severity_reserve_decision_eval", table_name="severity_reserve_decisions")
    op.drop_table("severity_reserve_decisions")
    op.drop_index("ix_severity_reserve_evaluations_snapshot_id", table_name="severity_reserve_evaluations")
    op.drop_index("ix_severity_reserve_evaluations_claim_id", table_name="severity_reserve_evaluations")
    op.drop_index("ix_severity_reserve_evaluations_organization_id", table_name="severity_reserve_evaluations")
    op.drop_index("ix_severity_reserve_eval_claim", table_name="severity_reserve_evaluations")
    op.drop_table("severity_reserve_evaluations")
    op.drop_index("ix_severity_reserve_snapshots_claim_id", table_name="severity_reserve_snapshots")
    op.drop_index("ix_severity_reserve_snapshots_organization_id", table_name="severity_reserve_snapshots")
    op.drop_index("ix_severity_reserve_snapshot_claim", table_name="severity_reserve_snapshots")
    op.drop_table("severity_reserve_snapshots")
