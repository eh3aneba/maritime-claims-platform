"""Track provider attachment byte acquisition in quarantine-only staging.

Revision ID: 0079_email_provider_attachment_quarantine
Revises: 0078_email_provider_source_integrity
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0079_email_provider_attachment_quarantine"
down_revision = "0078_email_provider_source_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_attachment_manifests",
        sa.Column("provider_attachment_id", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column(
            "acquired_claim_id",
            sa.Uuid(),
            sa.ForeignKey("claims.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column(
            "acquired_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("quarantine_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("acquired_file_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("acquired_file_size_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("malware_scan_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("acquisition_failure_code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("malware_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_attachment_acquired_claim",
        "email_attachment_manifests",
        ["acquired_claim_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_attachment_acquired_claim", table_name="email_attachment_manifests")
    op.drop_column("email_attachment_manifests", "malware_scanned_at")
    op.drop_column("email_attachment_manifests", "acquired_at")
    op.drop_column("email_attachment_manifests", "acquisition_failure_code")
    op.drop_column("email_attachment_manifests", "malware_scan_status")
    op.drop_column("email_attachment_manifests", "acquired_file_size_bytes")
    op.drop_column("email_attachment_manifests", "acquired_file_hash")
    op.drop_column("email_attachment_manifests", "quarantine_key")
    op.drop_column("email_attachment_manifests", "acquired_by_id")
    op.drop_column("email_attachment_manifests", "acquired_claim_id")
    op.drop_column("email_attachment_manifests", "provider_attachment_id")
