"""Add crash-safe provider checkpoint handoff state.

Revision ID: 0081_provider_checkpoint_handoff
Revises: 0080_email_provider_evidence_admission
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0081_provider_checkpoint_handoff"
down_revision = "0080_email_provider_evidence_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_adapter_runs",
        sa.Column(
            "checkpoint_handoff_status",
            sa.String(length=30),
            nullable=False,
            server_default="not_required",
        ),
    )
    op.add_column(
        "email_adapter_runs",
        sa.Column("checkpoint_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_adapter_runs",
        sa.Column("checkpoint_abandoned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_adapter_run_handoff",
        "email_adapter_runs",
        ["adapter_id", "checkpoint_handoff_status", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_email_adapter_run_handoff", table_name="email_adapter_runs")
    op.drop_column("email_adapter_runs", "checkpoint_abandoned_at")
    op.drop_column("email_adapter_runs", "checkpoint_acknowledged_at")
    op.drop_column("email_adapter_runs", "checkpoint_handoff_status")
