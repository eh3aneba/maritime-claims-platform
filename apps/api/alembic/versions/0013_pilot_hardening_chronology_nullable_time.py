"""Allow source-grounded chronology events without an explicit clock time.

Revision ID: 0013_pilot_hardening
Revises: 0012_initial_assessment_builder
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_pilot_hardening"
down_revision: Union[str, None] = "0012_initial_assessment_builder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("chronology_events", "occurred_on", existing_type=sa.Date(), nullable=True)
    op.alter_column("chronology_events", "occurred_time", existing_type=sa.Time(), nullable=True)


def downgrade() -> None:
    # Old schema cannot represent undated/relative events. Remove only those derived
    # chronology rows before restoring NOT NULL; underlying reviewed evidence remains.
    op.execute("DELETE FROM event_evidence WHERE event_id IN (SELECT id FROM chronology_events WHERE occurred_on IS NULL OR occurred_time IS NULL)")
    op.execute("DELETE FROM chronology_events WHERE occurred_on IS NULL OR occurred_time IS NULL")
    op.alter_column("chronology_events", "occurred_time", existing_type=sa.Time(), nullable=False)
    op.alter_column("chronology_events", "occurred_on", existing_type=sa.Date(), nullable=False)
