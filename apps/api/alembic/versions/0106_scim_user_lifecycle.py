"""add governed SCIM User provisioning lifecycle

Revision ID: 0106_scim_user_lifecycle
Revises: 0105_scim_provisioning_foundation
"""

from alembic import op
import sqlalchemy as sa

revision = "0106_scim_user_lifecycle"
down_revision = "0105_scim_provisioning_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scim_provisioning_profiles",
        sa.Column(
            "user_provisioning_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.create_table(
        "scim_user_provisioning_grants",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("email_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("grant_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_user_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.Uuid(), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=200), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["profile_id"], ["scim_provisioning_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["consumed_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_hash", name="uq_scim_user_grants_hash"),
    )
    op.create_index(
        op.f("ix_scim_user_provisioning_grants_organization_id"),
        "scim_user_provisioning_grants",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_provisioning_grants_profile_id"),
        "scim_user_provisioning_grants",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_provisioning_grants_consumed_user_id"),
        "scim_user_provisioning_grants",
        ["consumed_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_provisioning_grants_cancelled_by_id"),
        "scim_user_provisioning_grants",
        ["cancelled_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_provisioning_grants_created_by_id"),
        "scim_user_provisioning_grants",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "uq_scim_user_grants_org_email_pending",
        "scim_user_provisioning_grants",
        ["organization_id", "email_fingerprint"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND cancelled_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL AND cancelled_at IS NULL"),
    )
    op.create_index(
        "ix_scim_user_grants_org_lifecycle",
        "scim_user_provisioning_grants",
        ["organization_id", "expires_at", "consumed_at", "cancelled_at"],
        unique=False,
    )

    op.create_table(
        "scim_user_bindings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("created_profile_id", sa.Uuid(), nullable=False),
        sa.Column("created_profile_number", sa.Integer(), nullable=False),
        sa.Column("created_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("user_name_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("external_id_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["scim_user_provisioning_grants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_profile_id"],
            ["scim_provisioning_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_scim_user_bindings_org_user",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "external_id_fingerprint",
            name="uq_scim_user_bindings_org_external",
        ),
        sa.UniqueConstraint("grant_id", name="uq_scim_user_bindings_grant"),
    )
    op.create_index(
        op.f("ix_scim_user_bindings_organization_id"),
        "scim_user_bindings",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_bindings_user_id"),
        "scim_user_bindings",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_bindings_grant_id"),
        "scim_user_bindings",
        ["grant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_user_bindings_created_profile_id"),
        "scim_user_bindings",
        ["created_profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_scim_user_bindings_org_lifecycle",
        "scim_user_bindings",
        ["organization_id", "deactivated_at", "last_synced_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scim_user_bindings_org_lifecycle",
        table_name="scim_user_bindings",
    )
    op.drop_index(
        op.f("ix_scim_user_bindings_created_profile_id"),
        table_name="scim_user_bindings",
    )
    op.drop_index(
        op.f("ix_scim_user_bindings_grant_id"),
        table_name="scim_user_bindings",
    )
    op.drop_index(
        op.f("ix_scim_user_bindings_user_id"),
        table_name="scim_user_bindings",
    )
    op.drop_index(
        op.f("ix_scim_user_bindings_organization_id"),
        table_name="scim_user_bindings",
    )
    op.drop_table("scim_user_bindings")

    op.drop_index(
        "ix_scim_user_grants_org_lifecycle",
        table_name="scim_user_provisioning_grants",
    )
    op.drop_index(
        "uq_scim_user_grants_org_email_pending",
        table_name="scim_user_provisioning_grants",
    )
    op.drop_index(
        op.f("ix_scim_user_provisioning_grants_created_by_id"),
        table_name="scim_user_provisioning_grants",
    )
    op.drop_index(
        op.f("ix_scim_user_provisioning_grants_cancelled_by_id"),
        table_name="scim_user_provisioning_grants",
    )
    op.drop_index(
        op.f("ix_scim_user_provisioning_grants_consumed_user_id"),
        table_name="scim_user_provisioning_grants",
    )
    op.drop_index(
        op.f("ix_scim_user_provisioning_grants_profile_id"),
        table_name="scim_user_provisioning_grants",
    )
    op.drop_index(
        op.f("ix_scim_user_provisioning_grants_organization_id"),
        table_name="scim_user_provisioning_grants",
    )
    op.drop_table("scim_user_provisioning_grants")

    op.drop_column("scim_provisioning_profiles", "user_provisioning_enabled")
