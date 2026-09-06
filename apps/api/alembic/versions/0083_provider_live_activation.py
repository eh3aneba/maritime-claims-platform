"""add provider live activation state

Revision ID: 0083_provider_live_activation
Revises: 0082_provider_credential_lifecycle
"""

from alembic import op
import sqlalchemy as sa

revision = "0083_provider_live_activation"
down_revision = "0082_provider_credential_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_provider_adapters",
        sa.Column("live_execution_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "email_provider_adapters",
        sa.Column("live_execution_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_provider_adapters",
        sa.Column(
            "live_execution_enabled_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_email_provider_adapter_live_execution",
        "email_provider_adapters",
        ["organization_id", "live_execution_enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_provider_adapter_live_execution", table_name="email_provider_adapters")
    op.drop_column("email_provider_adapters", "live_execution_enabled_by_id")
    op.drop_column("email_provider_adapters", "live_execution_enabled_at")
    op.drop_column("email_provider_adapters", "live_execution_enabled")
