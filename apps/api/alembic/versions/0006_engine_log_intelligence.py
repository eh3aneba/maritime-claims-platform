"""engine log intelligence job type

Revision ID: 0006_engine_log_intelligence
Revises: 0005_human_ai_review
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006_engine_log_intelligence"
down_revision: Union[str, None] = "0005_human_ai_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL enums require an explicit additive migration for new queue jobs.
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_engine_log'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value directly. Recreate the pre-Phase-D enum.
    op.execute("DELETE FROM document_processing_jobs WHERE job_type = 'ai_extract_engine_log'")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type DROP DEFAULT")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE VARCHAR(50) USING job_type::text")
    op.execute("DROP TYPE processing_job_type")
    op.execute("CREATE TYPE processing_job_type AS ENUM ('extract_text', 'ai_extract_ce_report')")
    op.execute(
        "ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE processing_job_type USING job_type::processing_job_type"
    )
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type SET DEFAULT 'extract_text'")
