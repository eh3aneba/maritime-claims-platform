"""human ai review and approved claim facts

Revision ID: 0005_human_ai_review
Revises: 0004_ce_report_ai_intelligence
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_human_ai_review"
down_revision: Union[str, None] = "0004_ce_report_ai_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claim_facts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=220), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("source_segment_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_claim_facts_version"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_segment_id"], ["document_text_segments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "field_path", name="uq_claim_facts_org_claim_field"),
    )
    op.create_index("ix_claim_facts_organization_id", "claim_facts", ["organization_id"])
    op.create_index("ix_claim_facts_claim_id", "claim_facts", ["claim_id"])
    op.create_index("ix_claim_facts_source_extraction_id", "claim_facts", ["source_extraction_id"])
    op.create_index("ix_claim_facts_source_document_id", "claim_facts", ["source_document_id"])
    op.create_index("ix_claim_facts_org_claim", "claim_facts", ["organization_id", "claim_id"])

    op.create_table(
        "ai_feedback",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("ai_value", sa.JSON(), nullable=True),
        sa.Column("human_value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("action IN ('approved', 'edited', 'rejected')", name="ck_ai_feedback_action"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_feedback_organization_id", "ai_feedback", ["organization_id"])
    op.create_index("ix_ai_feedback_claim_id", "ai_feedback", ["claim_id"])
    op.create_index("ix_ai_feedback_document_id", "ai_feedback", ["document_id"])
    op.create_index("ix_ai_feedback_extraction_id", "ai_feedback", ["extraction_id"])
    op.create_index("ix_ai_feedback_reviewer_id", "ai_feedback", ["reviewer_id"])
    op.create_index("ix_ai_feedback_org_extraction_created", "ai_feedback", ["organization_id", "extraction_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_feedback_org_extraction_created", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_reviewer_id", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_extraction_id", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_document_id", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_claim_id", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_organization_id", table_name="ai_feedback")
    op.drop_table("ai_feedback")

    op.drop_index("ix_claim_facts_org_claim", table_name="claim_facts")
    op.drop_index("ix_claim_facts_source_document_id", table_name="claim_facts")
    op.drop_index("ix_claim_facts_source_extraction_id", table_name="claim_facts")
    op.drop_index("ix_claim_facts_claim_id", table_name="claim_facts")
    op.drop_index("ix_claim_facts_organization_id", table_name="claim_facts")
    op.drop_table("claim_facts")
