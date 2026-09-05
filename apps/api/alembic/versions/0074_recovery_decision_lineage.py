"""Recovery decision and action lineage.

Revision ID: 0074_recovery_decision_lineage
Revises: 0073_recovery_timebar_maturity
"""
import sqlalchemy as sa
from alembic import op

revision = "0074_recovery_decision_lineage"
down_revision = "0073_recovery_timebar_maturity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_pursuit_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("decision_key", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("counterparty_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("disposition", sa.String(24), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("basis_reference", sa.Text(), nullable=False),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("previous_decision_hash", sa.String(64), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["recovery_pursuit_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["counterparty_id"], ["recovery_counterparties.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "claim_id", "decision_key", "version",
            name="uq_recovery_pursuit_decision_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_recovery_pursuit_decision_version"),
        sa.CheckConstraint(
            "disposition IN ('pursue','monitor','do_not_pursue','close')",
            name="ck_recovery_pursuit_decision_disposition",
        ),
    )
    op.create_index(
        "ix_recovery_pursuit_decision_claim",
        "recovery_pursuit_decisions",
        ["organization_id", "claim_id", "decision_key", "version"],
    )
    op.create_index(
        "ix_recovery_pursuit_decisions_organization_id",
        "recovery_pursuit_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_recovery_pursuit_decisions_claim_id",
        "recovery_pursuit_decisions",
        ["claim_id"],
    )
    op.create_index(
        "ix_recovery_pursuit_decisions_decision_key",
        "recovery_pursuit_decisions",
        ["decision_key"],
    )

    op.create_table(
        "recovery_action_logs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("decision_key", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("action_number", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("external_status", sa.String(120), nullable=True),
        sa.Column("external_response_date", sa.Date(), nullable=True),
        sa.Column("previous_action_hash", sa.String(64), nullable=True),
        sa.Column("action_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["recovery_pursuit_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "claim_id", "decision_key", "action_number",
            name="uq_recovery_action_number",
        ),
        sa.CheckConstraint("action_number >= 1", name="ck_recovery_action_number"),
        sa.CheckConstraint(
            "action_type IN ('correspondence','demand','follow_up','response','note')",
            name="ck_recovery_action_type",
        ),
        sa.CheckConstraint(
            "direction IN ('inbound','outbound','internal')",
            name="ck_recovery_action_direction",
        ),
    )
    op.create_index(
        "ix_recovery_action_claim",
        "recovery_action_logs",
        ["organization_id", "claim_id", "decision_key", "action_number"],
    )
    op.create_index("ix_recovery_action_logs_organization_id", "recovery_action_logs", ["organization_id"])
    op.create_index("ix_recovery_action_logs_claim_id", "recovery_action_logs", ["claim_id"])
    op.create_index("ix_recovery_action_logs_decision_key", "recovery_action_logs", ["decision_key"])
    op.create_index("ix_recovery_action_logs_decision_id", "recovery_action_logs", ["decision_id"])


def downgrade() -> None:
    op.drop_index("ix_recovery_action_logs_decision_id", table_name="recovery_action_logs")
    op.drop_index("ix_recovery_action_logs_decision_key", table_name="recovery_action_logs")
    op.drop_index("ix_recovery_action_logs_claim_id", table_name="recovery_action_logs")
    op.drop_index("ix_recovery_action_logs_organization_id", table_name="recovery_action_logs")
    op.drop_index("ix_recovery_action_claim", table_name="recovery_action_logs")
    op.drop_table("recovery_action_logs")

    op.drop_index("ix_recovery_pursuit_decisions_decision_key", table_name="recovery_pursuit_decisions")
    op.drop_index("ix_recovery_pursuit_decisions_claim_id", table_name="recovery_pursuit_decisions")
    op.drop_index("ix_recovery_pursuit_decisions_organization_id", table_name="recovery_pursuit_decisions")
    op.drop_index("ix_recovery_pursuit_decision_claim", table_name="recovery_pursuit_decisions")
    op.drop_table("recovery_pursuit_decisions")
