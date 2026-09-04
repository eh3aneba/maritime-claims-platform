"""Append-only human technical investigation decisions.

Revision ID: 0069_technical_investigation_decision_lineage
Revises: 0068_claim_document_requirement_lineage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0069_technical_investigation_decision_lineage"
down_revision = "0068_claim_document_requirement_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technical_investigation_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("topic_key", sa.String(length=180), nullable=False),
        sa.Column("topic_kind", sa.String(length=40), nullable=False),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_decision_hash", sa.String(length=64), nullable=True),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "topic_key",
            "decision_number",
            name="uq_technical_investigation_decision_number",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_technical_investigation_decision_state_version"),
        sa.CheckConstraint("decision_number >= 1", name="ck_technical_investigation_decision_number"),
        sa.CheckConstraint(
            "action IN ('keep_open','supported_for_investigation','not_supported','needs_more_evidence')",
            name="ck_technical_investigation_decision_action",
        ),
    )
    op.create_index(
        "ix_technical_investigation_decisions_org_claim_topic",
        "technical_investigation_decisions",
        ["organization_id", "claim_id", "topic_key", "decision_number"],
    )
    op.create_index(
        "ix_technical_investigation_decisions_organization_id",
        "technical_investigation_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_technical_investigation_decisions_claim_id",
        "technical_investigation_decisions",
        ["claim_id"],
    )
    op.create_index(
        "ix_technical_investigation_decisions_topic_key",
        "technical_investigation_decisions",
        ["topic_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_technical_investigation_decisions_topic_key", table_name="technical_investigation_decisions")
    op.drop_index("ix_technical_investigation_decisions_claim_id", table_name="technical_investigation_decisions")
    op.drop_index("ix_technical_investigation_decisions_organization_id", table_name="technical_investigation_decisions")
    op.drop_index("ix_technical_investigation_decisions_org_claim_topic", table_name="technical_investigation_decisions")
    op.drop_table("technical_investigation_decisions")
