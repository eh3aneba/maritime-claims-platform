"""Marine rule human dispositions

Revision ID: 0059_marine_rule_dispositions
Revises: 0058_claim_intelligence
"""
import sqlalchemy as sa
from alembic import op

revision = "0059_marine_rule_dispositions"
down_revision = "0058_claim_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marine_rule_evaluation_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("rule_run_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("rule_id", sa.String(80), nullable=False),
        sa.Column("rule_version", sa.String(30), nullable=False),
        sa.Column("evaluation_hash", sa.String(64), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("edited_candidate_implication", sa.Text(), nullable=True),
        sa.Column("edited_recommended_action", sa.Text(), nullable=True),
        sa.Column("previous_decision_hash", sa.String(64), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_run_id"], ["rule_evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "rule_id",
            "evaluation_hash",
            "decision_number",
            name="uq_marine_rule_decision_number",
        ),
        sa.CheckConstraint("decision_number >= 1", name="ck_marine_rule_decision_number"),
        sa.CheckConstraint(
            "action IN ('accept','edit','dismiss','not_applicable')",
            name="ck_marine_rule_decision_action",
        ),
    )
    op.create_index(
        "ix_marine_rule_decision_eval",
        "marine_rule_evaluation_decisions",
        ["organization_id", "claim_id", "rule_id", "evaluation_hash", "decision_number"],
    )
    op.create_index(
        "ix_marine_rule_evaluation_decisions_claim_id",
        "marine_rule_evaluation_decisions",
        ["claim_id"],
    )
    op.create_index(
        "ix_marine_rule_evaluation_decisions_organization_id",
        "marine_rule_evaluation_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_marine_rule_evaluation_decisions_rule_run_id",
        "marine_rule_evaluation_decisions",
        ["rule_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_marine_rule_evaluation_decisions_rule_run_id", table_name="marine_rule_evaluation_decisions")
    op.drop_index("ix_marine_rule_evaluation_decisions_organization_id", table_name="marine_rule_evaluation_decisions")
    op.drop_index("ix_marine_rule_evaluation_decisions_claim_id", table_name="marine_rule_evaluation_decisions")
    op.drop_index("ix_marine_rule_decision_eval", table_name="marine_rule_evaluation_decisions")
    op.drop_table("marine_rule_evaluation_decisions")
