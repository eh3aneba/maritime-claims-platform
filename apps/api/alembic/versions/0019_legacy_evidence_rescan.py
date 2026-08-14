"""legacy evidence rescan and quarantine reconciliation

Revision ID: 0019_legacy_evidence_rescan
Revises: 0018_malware_quarantine
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_legacy_evidence_rescan"
down_revision = "0018_malware_quarantine"
branch_labels = None
depends_on = None

confidentiality_level = postgresql.ENUM(
    "internal",
    "confidential",
    "restricted",
    name="confidentiality_level",
    create_type=False,
)


def upgrade() -> None:
    # PostgreSQL enum values are append-only in this migration. No existing row is
    # relabelled; state changes occur only after a real scanner/operator action.
    op.execute(
        "ALTER TYPE document_malware_scan_status "
        "ADD VALUE IF NOT EXISTS 'infected_quarantined'"
    )
    op.execute(
        "ALTER TYPE document_malware_scan_status "
        "ADD VALUE IF NOT EXISTS 'scan_error'"
    )
    op.execute(
        "ALTER TYPE malware_quarantine_status ADD VALUE IF NOT EXISTS 'released'"
    )
    op.execute(
        "ALTER TYPE malware_quarantine_status ADD VALUE IF NOT EXISTS 'purged'"
    )
    op.execute(
        "ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'malware_rescan'"
    )

    op.add_column(
        "quarantined_uploads",
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("document_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column(
            "confidentiality_level",
            confidentiality_level,
            nullable=False,
            server_default="confidential",
        ),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("last_retried_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quarantined_uploads",
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_quarantined_uploads_source_document_id",
        "quarantined_uploads",
        "documents",
        ["source_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_quarantined_uploads_resolved_by_id",
        "quarantined_uploads",
        "users",
        ["resolved_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_quarantined_uploads_source_document_id",
        "quarantined_uploads",
        ["source_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quarantined_uploads_source_document_id",
        table_name="quarantined_uploads",
    )
    op.drop_constraint(
        "fk_quarantined_uploads_resolved_by_id",
        "quarantined_uploads",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_quarantined_uploads_source_document_id",
        "quarantined_uploads",
        type_="foreignkey",
    )
    for column in [
        "resolution_note",
        "resolved_at",
        "last_retried_at",
        "retry_count",
        "confidentiality_level",
        "document_type",
        "resolved_by_id",
        "source_document_id",
    ]:
        op.drop_column("quarantined_uploads", column)
    # PostgreSQL cannot safely remove enum values in place. Downgrade removes the
    # schema fields while leaving the append-only values available.

