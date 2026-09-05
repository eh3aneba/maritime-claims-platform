"""Initial Assessment source-state integrity.

Revision ID: 0075_assessment_source_integrity
Revises: 0074_recovery_decision_lineage
"""
import sqlalchemy as sa
from alembic import op

revision = "0075_assessment_source_integrity"
down_revision = "0074_recovery_decision_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("initial_assessments", sa.Column("source_snapshot", sa.JSON(), nullable=True))
    op.add_column("initial_assessments", sa.Column("source_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("initial_assessments", sa.Column("approved_content_hash", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_initial_assessments_source_fingerprint",
        "initial_assessments",
        ["source_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_initial_assessments_source_fingerprint", table_name="initial_assessments")
    op.drop_column("initial_assessments", "approved_content_hash")
    op.drop_column("initial_assessments", "source_fingerprint")
    op.drop_column("initial_assessments", "source_snapshot")
