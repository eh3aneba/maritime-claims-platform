"""Canonical claim fact provenance for AI and human-reviewed intake

Revision ID: 0065_canonical_claim_fact_provenance
Revises: 0064_governance_webhooks
"""

import sqlalchemy as sa
from alembic import op

revision = "0065_canonical_claim_fact_provenance"
down_revision = "0064_governance_webhooks"
branch_labels = None
depends_on = None


_PROVENANCE_CHECK = """
(
    provenance_kind = 'ai_review'
    AND source_extraction_id IS NOT NULL
    AND source_text_extraction_id IS NULL
)
OR
(
    provenance_kind = 'intake_review'
    AND source_extraction_id IS NULL
    AND source_text_extraction_id IS NOT NULL
)
"""


def upgrade() -> None:
    op.add_column(
        "claim_facts",
        sa.Column(
            "provenance_kind",
            sa.String(length=24),
            nullable=False,
            server_default="ai_review",
        ),
    )
    op.add_column(
        "claim_facts",
        sa.Column("source_text_extraction_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_claim_facts_text_extraction",
        "claim_facts",
        "document_text_extractions",
        ["source_text_extraction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_claim_facts_source_text_extraction_id",
        "claim_facts",
        ["source_text_extraction_id"],
    )
    op.alter_column(
        "claim_facts",
        "source_extraction_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_claim_facts_provenance_lineage",
        "claim_facts",
        _PROVENANCE_CHECK,
    )


def downgrade() -> None:
    # The pre-0065 schema cannot represent intake-reviewed facts without inventing
    # an AI extraction. Remove only those rows before restoring the original
    # non-null AI-extraction foreign key.
    op.execute("DELETE FROM claim_facts WHERE provenance_kind = 'intake_review'")
    op.drop_constraint(
        "ck_claim_facts_provenance_lineage",
        "claim_facts",
        type_="check",
    )
    op.alter_column(
        "claim_facts",
        "source_extraction_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_index("ix_claim_facts_source_text_extraction_id", table_name="claim_facts")
    op.drop_constraint(
        "fk_claim_facts_text_extraction",
        "claim_facts",
        type_="foreignkey",
    )
    op.drop_column("claim_facts", "source_text_extraction_id")
    op.drop_column("claim_facts", "provenance_kind")
