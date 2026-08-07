"""chief engineer report ai intelligence

Revision ID: 0004_ce_report_ai_intelligence
Revises: 0003_document_processing_foundation
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_ce_report_ai_intelligence"
down_revision: Union[str, None] = "0003_document_processing_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ai_run_status = sa.Enum("pending", "running", "completed", "failed", name="ai_run_status")
ai_semantic_kind = sa.Enum("fact", "opinion", "inference", name="ai_semantic_kind")
ai_review_status = sa.Enum("pending", "approved", "edited", "rejected", name="ai_review_status")


def upgrade() -> None:
    # PostgreSQL enum extension for the shared processing queue.
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_ce_report'")

    op.create_table(
        "ai_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("task", sa.String(length=100), nullable=False),
        sa.Column("status", ai_run_status, server_default="pending", nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_name", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=30), nullable=False),
        sa.Column("schema_name", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=30), nullable=False),
        sa.Column("input_text_hash", sa.String(length=64), nullable=False),
        sa.Column("input_char_count", sa.Integer(), nullable=False),
        sa.Column("document_type_candidate", sa.String(length=100), nullable=True),
        sa.Column("classification_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.Column("raw_response_id", sa.String(length=200), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("input_char_count >= 0", name="ck_ai_runs_input_char_count"),
        sa.CheckConstraint(
            "classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1)",
            name="ck_ai_runs_classification_confidence",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_runs_organization_id", "ai_runs", ["organization_id"])
    op.create_index("ix_ai_runs_claim_id", "ai_runs", ["claim_id"])
    op.create_index("ix_ai_runs_document_id", "ai_runs", ["document_id"])
    op.create_index("ix_ai_runs_status", "ai_runs", ["status"])
    op.create_index("ix_ai_runs_org_document_created", "ai_runs", ["organization_id", "document_id", "created_at"])

    op.create_table(
        "document_extractions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_segment_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("field_path", sa.String(length=220), nullable=False),
        sa.Column("semantic_kind", ai_semantic_kind, nullable=False),
        sa.Column("raw_value", sa.JSON(), nullable=True),
        sa.Column("normalized_value", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("source_locator_type", sa.String(length=30), nullable=True),
        sa.Column("source_locator_value", sa.String(length=100), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("source_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=True),
        sa.Column("human_status", ai_review_status, server_default="pending", nullable=False),
        sa.Column("approved_value", sa.JSON(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_document_extractions_confidence"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_run_id"], ["ai_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_segment_id"], ["document_text_segments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ai_run_id", "field_path", name="uq_document_extractions_run_field"),
    )
    op.create_index("ix_document_extractions_organization_id", "document_extractions", ["organization_id"])
    op.create_index("ix_document_extractions_claim_id", "document_extractions", ["claim_id"])
    op.create_index("ix_document_extractions_document_id", "document_extractions", ["document_id"])
    op.create_index("ix_document_extractions_ai_run_id", "document_extractions", ["ai_run_id"])
    op.create_index("ix_document_extractions_org_document", "document_extractions", ["organization_id", "document_id"])
    op.create_index("ix_document_extractions_review", "document_extractions", ["organization_id", "human_status"])


def downgrade() -> None:
    op.drop_index("ix_document_extractions_review", table_name="document_extractions")
    op.drop_index("ix_document_extractions_org_document", table_name="document_extractions")
    op.drop_index("ix_document_extractions_ai_run_id", table_name="document_extractions")
    op.drop_index("ix_document_extractions_document_id", table_name="document_extractions")
    op.drop_index("ix_document_extractions_claim_id", table_name="document_extractions")
    op.drop_index("ix_document_extractions_organization_id", table_name="document_extractions")
    op.drop_table("document_extractions")

    op.drop_index("ix_ai_runs_org_document_created", table_name="ai_runs")
    op.drop_index("ix_ai_runs_status", table_name="ai_runs")
    op.drop_index("ix_ai_runs_document_id", table_name="ai_runs")
    op.drop_index("ix_ai_runs_claim_id", table_name="ai_runs")
    op.drop_index("ix_ai_runs_organization_id", table_name="ai_runs")
    op.drop_table("ai_runs")

    ai_review_status.drop(op.get_bind(), checkfirst=True)
    ai_semantic_kind.drop(op.get_bind(), checkfirst=True)
    ai_run_status.drop(op.get_bind(), checkfirst=True)

    # PostgreSQL cannot remove a single enum value directly; recreate the pre-Phase-B type.
    op.execute("DELETE FROM document_processing_jobs WHERE job_type = 'ai_extract_ce_report'")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type DROP DEFAULT")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE VARCHAR(50) USING job_type::text")
    op.execute("DROP TYPE processing_job_type")
    op.execute("CREATE TYPE processing_job_type AS ENUM ('extract_text')")
    op.execute(
        "ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE processing_job_type USING job_type::processing_job_type"
    )
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type SET DEFAULT 'extract_text'")
