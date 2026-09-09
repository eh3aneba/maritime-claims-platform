"""add signed preservation signal intake profiles

Revision ID: 0109_preservation_signal_intake
Revises: 0108_legal_hold_proposals
"""

from alembic import op
import sqlalchemy as sa

revision = "0109_preservation_signal_intake"
down_revision = "0108_legal_hold_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preservation_signal_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allowed_hold_sources", sa.JSON(), nullable=False),
        sa.Column("secret_salt", sa.String(length=64), nullable=False),
        sa.Column("secret_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("secret_reference", sa.String(length=180), nullable=False),
        sa.Column("previous_secret_salt", sa.String(length=64), nullable=True),
        sa.Column("previous_secret_version", sa.Integer(), nullable=True),
        sa.Column("previous_secret_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
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
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_psp_org_name"),
    )
    op.create_index(
        op.f("ix_preservation_signal_profiles_organization_id"),
        "preservation_signal_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_preservation_signal_profiles_created_by_id"),
        "preservation_signal_profiles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_preservation_signal_profiles_updated_by_id"),
        "preservation_signal_profiles",
        ["updated_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_psp_org_enabled",
        "preservation_signal_profiles",
        ["organization_id", "enabled", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_psp_org_enabled", table_name="preservation_signal_profiles")
    op.drop_index(
        op.f("ix_preservation_signal_profiles_updated_by_id"),
        table_name="preservation_signal_profiles",
    )
    op.drop_index(
        op.f("ix_preservation_signal_profiles_created_by_id"),
        table_name="preservation_signal_profiles",
    )
    op.drop_index(
        op.f("ix_preservation_signal_profiles_organization_id"),
        table_name="preservation_signal_profiles",
    )
    op.drop_table("preservation_signal_profiles")
