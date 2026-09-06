"""Add non-secret provider credential reference lifecycle metadata.

Revision ID: 0082_provider_credential_lifecycle
Revises: 0081_provider_checkpoint_handoff
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0082_provider_credential_lifecycle"
down_revision = "0081_provider_checkpoint_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_provider_adapters",
        sa.Column(
            "credential_reference_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "email_provider_adapters",
        sa.Column("credential_reference_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_provider_adapters", "credential_reference_changed_at")
    op.drop_column("email_provider_adapters", "credential_reference_version")
