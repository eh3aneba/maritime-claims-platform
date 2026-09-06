"""Bind staged inbound email to its configured provider source.

Revision ID: 0078_email_provider_source_integrity
Revises: 0077_correspondence_request_context
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0078_email_provider_source_integrity"
down_revision = "0077_correspondence_request_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable by design: historical connection-only webhook rows predate provider-source
    # authority and must remain readable without retroactively inventing provenance.
    op.add_column(
        "ingested_email_messages",
        sa.Column(
            "adapter_id",
            sa.Uuid(),
            sa.ForeignKey("email_provider_adapters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ingested_email_messages_adapter_id",
        "ingested_email_messages",
        ["adapter_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingested_email_messages_adapter_id",
        table_name="ingested_email_messages",
    )
    op.drop_column("ingested_email_messages", "adapter_id")
