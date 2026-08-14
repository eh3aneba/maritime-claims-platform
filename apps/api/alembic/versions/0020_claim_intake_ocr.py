"""human-approved claim intake and local OCR foundation

Revision ID: 0020_claim_intake_ocr
Revises: 0019_legacy_evidence_rescan
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020_claim_intake_ocr"
down_revision = "0019_legacy_evidence_rescan"
branch_labels = None
depends_on = None

claim_intake_status = postgresql.ENUM(
    "processing",
    "pending_review",
    "approved",
    "rejected",
    "failed",
    "infected",
    "scan_error",
    name="claim_intake_status",
    create_type=False,
)
document_malware_scan_status = postgresql.ENUM(
    "legacy_unscanned",
    "clean",
    "infected_quarantined",
    "scan_error",
    name="document_malware_scan_status",
    create_type=False,
)
processing_job_status = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    name="processing_job_status",
    create_type=False,
)


def upgrade() -> None:
    claim_intake_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "claim_intake_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_claim_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("malware_scan_status", document_malware_scan_status, nullable=False),
        sa.Column("malware_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("threat_name", sa.String(length=255), nullable=True),
        sa.Column("scan_error", sa.Text(), nullable=True),
        sa.Column("status", claim_intake_status, nullable=False, server_default="processing"),
        sa.Column("extraction_method", sa.String(length=100), nullable=True),
        sa.Column("ocr_languages", sa.String(length=50), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extracted_segments", sa.JSON(), nullable=True),
        sa.Column("extraction_warnings", sa.JSON(), nullable=True),
        sa.Column("classification_candidate", sa.String(length=100), nullable=True),
        sa.Column("classification_confidence", sa.Integer(), nullable=True),
        sa.Column("classification_rule", sa.String(length=255), nullable=True),
        sa.Column("extracted_fields", sa.JSON(), nullable=True),
        sa.Column("field_evidence", sa.JSON(), nullable=True),
        sa.Column("review_payload", sa.JSON(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approved_claim_id"),
        sa.UniqueConstraint("source_document_id"),
        sa.UniqueConstraint("organization_id", "file_hash", name="uq_claim_intake_org_hash"),
    )
    op.create_index(
        "ix_claim_intake_drafts_organization_id", "claim_intake_drafts", ["organization_id"]
    )
    op.create_index(
        "ix_claim_intake_org_status", "claim_intake_drafts", ["organization_id", "status"]
    )

    op.create_table(
        "claim_intake_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("intake_draft_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("status", processing_job_status, nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["intake_draft_id"], ["claim_intake_drafts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intake_draft_id", name="uq_claim_intake_processing_job_draft"),
    )
    op.create_index(
        "ix_claim_intake_processing_jobs_organization_id",
        "claim_intake_processing_jobs",
        ["organization_id"],
    )
    op.create_index(
        "ix_claim_intake_processing_jobs_intake_draft_id",
        "claim_intake_processing_jobs",
        ["intake_draft_id"],
    )
    op.create_index(
        "ix_claim_intake_jobs_status_available",
        "claim_intake_processing_jobs",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_claim_intake_jobs_status_available", table_name="claim_intake_processing_jobs"
    )
    op.drop_index(
        "ix_claim_intake_processing_jobs_intake_draft_id", table_name="claim_intake_processing_jobs"
    )
    op.drop_index(
        "ix_claim_intake_processing_jobs_organization_id", table_name="claim_intake_processing_jobs"
    )
    op.drop_table("claim_intake_processing_jobs")
    op.drop_index("ix_claim_intake_org_status", table_name="claim_intake_drafts")
    op.drop_index("ix_claim_intake_drafts_organization_id", table_name="claim_intake_drafts")
    op.drop_table("claim_intake_drafts")
    claim_intake_status.drop(op.get_bind(), checkfirst=True)
