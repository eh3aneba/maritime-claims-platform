"""Append-only human financial cost review decisions.

Revision ID: 0070_cost_review_decision_lineage
Revises: 0069_technical_investigation_decision_lineage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0070_cost_review_decision_lineage"
down_revision = "0069_technical_investigation_decision_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_review_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.String(length=80), nullable=False),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("item_snapshot", sa.JSON(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_decision_hash", sa.String(length=64), nullable=True),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "item_key",
            "decision_number",
            name="uq_cost_review_decision_number",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_cost_review_decision_state_version"),
        sa.CheckConstraint("decision_number >= 1", name="ck_cost_review_decision_number"),
        sa.CheckConstraint(
            "status IN ('claimed','under_review','potentially_recoverable','potentially_non_recoverable','accepted','rejected','paid')",
            name="ck_cost_review_decision_status",
        ),
    )
    op.create_index(
        "ix_cost_review_decisions_org_claim_item",
        "cost_review_decisions",
        ["organization_id", "claim_id", "item_key", "decision_number"],
    )
    op.create_index(
        "ix_cost_review_decisions_organization_id",
        "cost_review_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_cost_review_decisions_claim_id",
        "cost_review_decisions",
        ["claim_id"],
    )
    op.create_index(
        "ix_cost_review_decisions_item_key",
        "cost_review_decisions",
        ["item_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_cost_review_decisions_item_key", table_name="cost_review_decisions")
    op.drop_index("ix_cost_review_decisions_claim_id", table_name="cost_review_decisions")
    op.drop_index("ix_cost_review_decisions_organization_id", table_name="cost_review_decisions")
    op.drop_index("ix_cost_review_decisions_org_claim_item", table_name="cost_review_decisions")
    op.drop_table("cost_review_decisions")
