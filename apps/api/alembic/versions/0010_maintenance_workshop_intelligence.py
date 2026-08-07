"""maintenance and workshop intelligence job types

Revision ID: 0010_maintenance_workshop_intelligence
Revises: 0009_rule_driven_tasks_and_requests
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010_maintenance_workshop_intelligence"
down_revision: Union[str, None] = "0009_rule_driven_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_running_hours'")
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_pms_history'")
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_workshop_report'")


def downgrade() -> None:
    op.execute("DELETE FROM document_processing_jobs WHERE job_type IN ('ai_extract_running_hours','ai_extract_pms_history','ai_extract_workshop_report')")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type DROP DEFAULT")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE VARCHAR(50) USING job_type::text")
    op.execute("DROP TYPE processing_job_type")
    op.execute("CREATE TYPE processing_job_type AS ENUM ('extract_text', 'ai_extract_ce_report', 'ai_extract_engine_log')")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE processing_job_type USING job_type::processing_job_type")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type SET DEFAULT 'extract_text'")
