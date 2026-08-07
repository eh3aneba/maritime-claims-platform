"""document processing foundation

Revision ID: 0003_document_processing_foundation
Revises: 0002_claims_api_foundation
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_document_processing_foundation"
down_revision: Union[str, None] = "0002_claims_api_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

processing_job_type = sa.Enum("extract_text", name="processing_job_type")
processing_job_status = sa.Enum("pending", "running", "completed", "failed", name="processing_job_status")


def upgrade() -> None:
    op.create_table(
        "document_processing_jobs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("job_type", processing_job_type, server_default="extract_text", nullable=False),
        sa.Column("status", processing_job_status, server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_processing_jobs_attempt_count"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_processing_jobs_max_attempts"),
    )
    op.create_index("ix_document_processing_jobs_organization_id", "document_processing_jobs", ["organization_id"])
    op.create_index("ix_document_processing_jobs_claim_id", "document_processing_jobs", ["claim_id"])
    op.create_index("ix_document_processing_jobs_document_id", "document_processing_jobs", ["document_id"])
    op.create_index("ix_processing_jobs_status_available", "document_processing_jobs", ["status", "available_at"])
    op.create_index("ix_processing_jobs_org_document", "document_processing_jobs", ["organization_id", "document_id"])

    op.create_table(
        "document_text_extractions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_method", sa.String(length=80), nullable=False),
        sa.Column("extractor_version", sa.String(length=50), nullable=False),
        sa.Column("char_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("segment_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requires_ocr", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_document_text_extractions_document"),
        sa.CheckConstraint("char_count >= 0", name="ck_document_text_extractions_char_count"),
        sa.CheckConstraint("segment_count >= 0", name="ck_document_text_extractions_segment_count"),
    )
    op.create_index("ix_document_text_extractions_organization_id", "document_text_extractions", ["organization_id"])
    op.create_index("ix_document_text_extractions_document_id", "document_text_extractions", ["document_id"])

    op.create_table(
        "document_text_segments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("locator_type", sa.String(length=30), nullable=False),
        sa.Column("locator_value", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extraction_id"], ["document_text_extractions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_id", "segment_index", name="uq_document_text_segment_index"),
        sa.CheckConstraint("segment_index >= 0", name="ck_document_text_segments_index"),
        sa.CheckConstraint("char_count >= 0", name="ck_document_text_segments_char_count"),
    )
    op.create_index("ix_document_text_segments_organization_id", "document_text_segments", ["organization_id"])
    op.create_index("ix_document_text_segments_document_id", "document_text_segments", ["document_id"])
    op.create_index("ix_document_text_segments_extraction_id", "document_text_segments", ["extraction_id"])
    op.create_index("ix_document_text_segments_document", "document_text_segments", ["document_id", "segment_index"])


def downgrade() -> None:
    op.drop_index("ix_document_text_segments_document", table_name="document_text_segments")
    op.drop_index("ix_document_text_segments_extraction_id", table_name="document_text_segments")
    op.drop_index("ix_document_text_segments_document_id", table_name="document_text_segments")
    op.drop_index("ix_document_text_segments_organization_id", table_name="document_text_segments")
    op.drop_table("document_text_segments")

    op.drop_index("ix_document_text_extractions_document_id", table_name="document_text_extractions")
    op.drop_index("ix_document_text_extractions_organization_id", table_name="document_text_extractions")
    op.drop_table("document_text_extractions")

    op.drop_index("ix_processing_jobs_org_document", table_name="document_processing_jobs")
    op.drop_index("ix_processing_jobs_status_available", table_name="document_processing_jobs")
    op.drop_index("ix_document_processing_jobs_document_id", table_name="document_processing_jobs")
    op.drop_index("ix_document_processing_jobs_claim_id", table_name="document_processing_jobs")
    op.drop_index("ix_document_processing_jobs_organization_id", table_name="document_processing_jobs")
    op.drop_table("document_processing_jobs")

    processing_job_status.drop(op.get_bind(), checkfirst=True)
    processing_job_type.drop(op.get_bind(), checkfirst=True)
