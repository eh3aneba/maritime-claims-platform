"""Bind adjustments to financial source state and structured controls.

Revision ID: 0071_adjustment_source_state_controls
Revises: 0070_cost_review_decision_lineage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0071_adjustment_source_state_controls"
down_revision = "0070_cost_review_decision_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "adjustment_statements",
        sa.Column("rebased_from_statement_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "adjustment_statements",
        sa.Column("source_manifest_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "adjustment_statements",
        sa.Column("source_state_hash", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_adjustment_statement_rebased_from",
        "adjustment_statements",
        "adjustment_statements",
        ["rebased_from_statement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_adjustment_statements_rebased_from_statement_id",
        "adjustment_statements",
        ["rebased_from_statement_id"],
    )
    op.create_index(
        "ix_adjustment_statements_source_state_hash",
        "adjustment_statements",
        ["source_state_hash"],
    )
    op.create_check_constraint(
        "ck_adjustment_source_manifest_version",
        "adjustment_statements",
        "source_manifest_version >= 1",
    )

    op.add_column(
        "adjustment_lines",
        sa.Column("financial_controls", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )

    # Existing statements predate state-bound Adjustment source identity. Leave
    # source_state_hash NULL intentionally so they render as legacy_unbound rather
    # than pretending a historical statement is current against today's evidence.


def downgrade() -> None:
    op.drop_column("adjustment_lines", "financial_controls")
    op.drop_constraint("ck_adjustment_source_manifest_version", "adjustment_statements", type_="check")
    op.drop_index("ix_adjustment_statements_source_state_hash", table_name="adjustment_statements")
    op.drop_index("ix_adjustment_statements_rebased_from_statement_id", table_name="adjustment_statements")
    op.drop_constraint("fk_adjustment_statement_rebased_from", "adjustment_statements", type_="foreignkey")
    op.drop_column("adjustment_statements", "source_state_hash")
    op.drop_column("adjustment_statements", "source_manifest_version")
    op.drop_column("adjustment_statements", "rebased_from_statement_id")
