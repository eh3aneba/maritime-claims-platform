"""add tenant MFA policy enforcement state

Revision ID: 0096_mfa_policy_enforcement
Revises: 0095_totp_mfa_foundation
"""

from alembic import op
import sqlalchemy as sa

revision = "0096_mfa_policy_enforcement"
down_revision = "0095_totp_mfa_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_policies",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("required_roles", sa.JSON(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_mfa_policies_organization_id",
        ),
    )
    op.create_index(
        op.f("ix_mfa_policies_updated_by_id"),
        "mfa_policies",
        ["updated_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mfa_policies_updated_by_id"),
        table_name="mfa_policies",
    )
    op.drop_table("mfa_policies")
