"""versioned advanced financial adjustment controls

Revision ID: 0024_adjustment_controls
Revises: 0023_correspondence_centre
"""

import sqlalchemy as sa

from alembic import op


revision = "0024_adjustment_controls"
down_revision = "0023_correspondence_centre"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = sa.Enum("draft", "under_review", "approved", "rejected", name="adjustment_status")
    treatment = sa.Enum("pending", "included", "excluded", "apportioned", "credit", name="adjustment_treatment")
    basis = sa.Enum("unallocated", "particular_average", "general_average", "sue_and_labour", "rdc", "other", "not_applicable", name="adjustment_basis")

    op.create_table(
        "adjustment_statements",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", status, server_default="draft", nullable=False),
        sa.Column("deductible_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("deductible_basis", sa.Text(), nullable=True),
        sa.Column("other_deduction_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("other_deduction_basis", sa.Text(), nullable=True),
        sa.Column("gross_claimed", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("gross_considered", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("net_adjusted", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("source_manifest", sa.JSON(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("deductible_amount >= 0", name="ck_adjustment_deductible_nonnegative"),
        sa.CheckConstraint("other_deduction_amount >= 0", name="ck_adjustment_other_deduction_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "version", name="uq_adjustment_statement_claim_version"),
    )
    op.create_index("ix_adjustment_statements_organization_id", "adjustment_statements", ["organization_id"], unique=False)
    op.create_index("ix_adjustment_statements_claim_id", "adjustment_statements", ["claim_id"], unique=False)
    op.create_index("ix_adjustment_statements_org_claim_created", "adjustment_statements", ["organization_id", "claim_id", "created_at"], unique=False)

    op.create_table(
        "adjustment_lines",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("cost_item_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("supplier", sa.String(length=255), nullable=True),
        sa.Column("document_number", sa.String(length=120), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("claimed_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("considered_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("treatment", treatment, server_default="pending", nullable=False),
        sa.Column("basis", basis, server_default="unallocated", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("claimed_amount >= 0", name="ck_adjustment_line_claimed_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_id"], ["adjustment_statements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cost_item_id"], ["cost_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_adjustment_lines_organization_id", "adjustment_lines", ["organization_id"], unique=False)
    op.create_index("ix_adjustment_lines_claim_id", "adjustment_lines", ["claim_id"], unique=False)
    op.create_index("ix_adjustment_lines_statement_id", "adjustment_lines", ["statement_id"], unique=False)
    op.create_index("ix_adjustment_lines_cost_item_id", "adjustment_lines", ["cost_item_id"], unique=False)
    op.create_index("ix_adjustment_lines_source_document_id", "adjustment_lines", ["source_document_id"], unique=False)
    op.create_index("ix_adjustment_lines_statement_order", "adjustment_lines", ["statement_id", "sort_order"], unique=False)
    op.create_index("ix_adjustment_lines_org_claim", "adjustment_lines", ["organization_id", "claim_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_adjustment_lines_org_claim", table_name="adjustment_lines")
    op.drop_index("ix_adjustment_lines_statement_order", table_name="adjustment_lines")
    op.drop_index("ix_adjustment_lines_source_document_id", table_name="adjustment_lines")
    op.drop_index("ix_adjustment_lines_cost_item_id", table_name="adjustment_lines")
    op.drop_index("ix_adjustment_lines_statement_id", table_name="adjustment_lines")
    op.drop_index("ix_adjustment_lines_claim_id", table_name="adjustment_lines")
    op.drop_index("ix_adjustment_lines_organization_id", table_name="adjustment_lines")
    op.drop_table("adjustment_lines")
    op.drop_index("ix_adjustment_statements_org_claim_created", table_name="adjustment_statements")
    op.drop_index("ix_adjustment_statements_claim_id", table_name="adjustment_statements")
    op.drop_index("ix_adjustment_statements_organization_id", table_name="adjustment_statements")
    op.drop_table("adjustment_statements")
    sa.Enum(name="adjustment_basis").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="adjustment_treatment").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="adjustment_status").drop(op.get_bind(), checkfirst=True)
