"""Append-only canonical ClaimFact revision history

Revision ID: 0066_claim_fact_revision_history
Revises: 0065_canonical_claim_fact_provenance
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0066_claim_fact_revision_history"
down_revision = "0065_canonical_claim_fact_provenance"
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
    op.create_table(
        "claim_fact_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=220), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("provenance_kind", sa.String(length=24), nullable=False),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=True),
        sa.Column("source_text_extraction_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("source_segment_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1", name="ck_claim_fact_revisions_version"),
        sa.CheckConstraint(_PROVENANCE_CHECK, name="ck_claim_fact_revisions_provenance_lineage"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_text_extraction_id"], ["document_text_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_segment_id"], ["document_text_segments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "field_path",
            "version",
            name="uq_claim_fact_revisions_org_claim_field_version",
        ),
    )
    op.create_index(
        "ix_claim_fact_revisions_org_claim_field",
        "claim_fact_revisions",
        ["organization_id", "claim_id", "field_path"],
    )
    op.create_index("ix_claim_fact_revisions_organization_id", "claim_fact_revisions", ["organization_id"])
    op.create_index("ix_claim_fact_revisions_claim_id", "claim_fact_revisions", ["claim_id"])
    op.create_index("ix_claim_fact_revisions_source_extraction_id", "claim_fact_revisions", ["source_extraction_id"])
    op.create_index("ix_claim_fact_revisions_source_text_extraction_id", "claim_fact_revisions", ["source_text_extraction_id"])
    op.create_index("ix_claim_fact_revisions_source_document_id", "claim_fact_revisions", ["source_document_id"])

    revision_table = sa.table(
        "claim_fact_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("claim_id", sa.Uuid()),
        sa.column("field_path", sa.String()),
        sa.column("value", sa.JSON()),
        sa.column("provenance_kind", sa.String()),
        sa.column("source_extraction_id", sa.Uuid()),
        sa.column("source_text_extraction_id", sa.Uuid()),
        sa.column("source_document_id", sa.Uuid()),
        sa.column("source_segment_id", sa.Uuid()),
        sa.column("approved_by_id", sa.Uuid()),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("version", sa.Integer()),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT organization_id, claim_id, field_path, value, provenance_kind, "
            "source_extraction_id, source_text_extraction_id, source_document_id, "
            "source_segment_id, approved_by_id, approved_at, version FROM claim_facts"
        )
    ).mappings()
    payload = [dict(row, id=uuid4()) for row in rows]
    if payload:
        op.bulk_insert(revision_table, payload)


def downgrade() -> None:
    op.drop_index("ix_claim_fact_revisions_source_document_id", table_name="claim_fact_revisions")
    op.drop_index("ix_claim_fact_revisions_source_text_extraction_id", table_name="claim_fact_revisions")
    op.drop_index("ix_claim_fact_revisions_source_extraction_id", table_name="claim_fact_revisions")
    op.drop_index("ix_claim_fact_revisions_claim_id", table_name="claim_fact_revisions")
    op.drop_index("ix_claim_fact_revisions_organization_id", table_name="claim_fact_revisions")
    op.drop_index("ix_claim_fact_revisions_org_claim_field", table_name="claim_fact_revisions")
    op.drop_table("claim_fact_revisions")
