"""controlled evidence document versioning and replacement

Revision ID: 0021_evidence_versioning
Revises: 0020_claim_intake_ocr
"""

import sqlalchemy as sa

from alembic import op

revision = "0021_evidence_versioning"
down_revision = "0020_claim_intake_ocr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("document_family_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("documents", sa.Column("replacement_reason", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("documents", sa.Column("superseded_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_documents_superseded_by_id_users",
        "documents",
        "users",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Every pre-existing evidence record starts as the sole active member of its
    # own family. No bytes, metadata or source links are rewritten.
    op.execute(
        "UPDATE documents SET document_family_id = id "
        "WHERE document_family_id IS NULL"
    )
    op.alter_column("documents", "document_family_id", nullable=False)
    op.create_index(
        "ix_documents_org_family",
        "documents",
        ["organization_id", "claim_id", "document_family_id"],
    )
    op.create_unique_constraint(
        "uq_documents_family_version",
        "documents",
        ["organization_id", "claim_id", "document_family_id", "version_number"],
    )
    op.create_index(
        "uq_documents_active_family",
        "documents",
        ["organization_id", "claim_id", "document_family_id"],
        unique=True,
        postgresql_where=sa.text("is_current AND deleted_at IS NULL"),
    )

    op.add_column(
        "quarantined_uploads",
        sa.Column("replaces_document_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("replacement_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_quarantined_replaces_document",
        "quarantined_uploads",
        "documents",
        ["replaces_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_quarantined_uploads_replaces_document_id",
        "quarantined_uploads",
        ["replaces_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quarantined_uploads_replaces_document_id",
        table_name="quarantined_uploads",
    )
    op.drop_constraint(
        "fk_quarantined_replaces_document",
        "quarantined_uploads",
        type_="foreignkey",
    )
    op.drop_column("quarantined_uploads", "replacement_reason")
    op.drop_column("quarantined_uploads", "replaces_document_id")

    op.drop_index("uq_documents_active_family", table_name="documents")
    op.drop_constraint(
        "uq_documents_family_version",
        "documents",
        type_="unique",
    )
    op.drop_index("ix_documents_org_family", table_name="documents")
    op.drop_constraint(
        "fk_documents_superseded_by_id_users",
        "documents",
        type_="foreignkey",
    )
    op.drop_column("documents", "superseded_by_id")
    op.drop_column("documents", "superseded_at")
    op.drop_column("documents", "replacement_reason")
    op.drop_column("documents", "is_current")
    op.drop_column("documents", "document_family_id")
