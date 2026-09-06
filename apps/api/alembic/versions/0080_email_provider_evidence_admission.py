"""Add explicit provider attachment Evidence-admission provenance.

Revision ID: 0080_email_provider_evidence_admission
Revises: 0079_email_provider_attachment_quarantine
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0080_email_provider_evidence_admission"
down_revision = "0079_email_provider_attachment_quarantine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "source_email_attachment_manifest_id",
            sa.Uuid(),
            sa.ForeignKey("email_attachment_manifests.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("source_admission_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "uq_documents_source_email_attachment_manifest",
        "documents",
        ["source_email_attachment_manifest_id"],
        unique=True,
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("evidence_admission_failure_code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "email_attachment_manifests",
        sa.Column("evidence_admission_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_attachment_manifests", "evidence_admission_attempted_at")
    op.drop_column("email_attachment_manifests", "evidence_admission_failure_code")
    op.drop_index("uq_documents_source_email_attachment_manifest", table_name="documents")
    op.drop_column("documents", "source_admission_note")
    op.drop_column("documents", "source_email_attachment_manifest_id")
