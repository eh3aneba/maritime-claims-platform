"""controlled immutable claim pack exports

Revision ID: 0022_claim_pack_exports
Revises: 0021_evidence_versioning
"""

import sqlalchemy as sa

from alembic import op


revision = "0022_claim_pack_exports"
down_revision = "0021_evidence_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    export_format = sa.Enum("pdf", "xlsx", name="claim_pack_format")
    op.create_table(
        "claim_pack_exports",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("generated_by_id", sa.Uuid(), nullable=True),
        sa.Column("export_format", export_format, nullable=False),
        sa.Column(
            "snapshot_schema_version",
            sa.String(length=30),
            server_default="1.0",
            nullable=False,
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("generation_note", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_claim_pack_exports_claim_id",
        "claim_pack_exports",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        "ix_claim_pack_exports_organization_id",
        "claim_pack_exports",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_claim_pack_exports_org_claim_created",
        "claim_pack_exports",
        ["organization_id", "claim_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_claim_pack_exports_org_claim_created",
        table_name="claim_pack_exports",
    )
    op.drop_index(
        "ix_claim_pack_exports_organization_id",
        table_name="claim_pack_exports",
    )
    op.drop_index(
        "ix_claim_pack_exports_claim_id",
        table_name="claim_pack_exports",
    )
    op.drop_table("claim_pack_exports")
    sa.Enum(name="claim_pack_format").drop(op.get_bind(), checkfirst=True)
