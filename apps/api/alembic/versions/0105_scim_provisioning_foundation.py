"""add governed SCIM provisioning control-plane foundation

Revision ID: 0105_scim_provisioning_foundation
Revises: 0104_saml_mfa_assurance
"""

from alembic import op
import sqlalchemy as sa

revision = "0105_scim_provisioning_foundation"
down_revision = "0104_saml_mfa_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scim_provisioning_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("client_name", sa.String(length=160), nullable=False),
        sa.Column("service_base_path", sa.String(length=160), nullable=False),
        sa.Column("token_ttl_days", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_profile_hash", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "profile_number",
            name="uq_scim_provisioning_profiles_org_number",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "profile_hash",
            name="uq_scim_provisioning_profiles_org_hash",
        ),
    )
    op.create_index(
        op.f("ix_scim_provisioning_profiles_organization_id"),
        "scim_provisioning_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_provisioning_profiles_created_by_id"),
        "scim_provisioning_profiles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_scim_provisioning_profiles_org_number",
        "scim_provisioning_profiles",
        ["organization_id", "profile_number"],
        unique=False,
    )

    op.create_table(
        "scim_provisioning_tokens",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=200), nullable=True),
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
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_digest",
            name="uq_scim_provisioning_tokens_digest",
        ),
    )
    op.create_index(
        op.f("ix_scim_provisioning_tokens_organization_id"),
        "scim_provisioning_tokens",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_provisioning_tokens_profile_id"),
        "scim_provisioning_tokens",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_provisioning_tokens_revoked_by_id"),
        "scim_provisioning_tokens",
        ["revoked_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scim_provisioning_tokens_created_by_id"),
        "scim_provisioning_tokens",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "uq_scim_provisioning_tokens_profile_unrevoked",
        "scim_provisioning_tokens",
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_scim_provisioning_tokens_org_lifecycle",
        "scim_provisioning_tokens",
        ["organization_id", "expires_at", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scim_provisioning_tokens_org_lifecycle",
        table_name="scim_provisioning_tokens",
    )
    op.drop_index(
        "uq_scim_provisioning_tokens_profile_unrevoked",
        table_name="scim_provisioning_tokens",
    )
    op.drop_index(
        op.f("ix_scim_provisioning_tokens_created_by_id"),
        table_name="scim_provisioning_tokens",
    )
    op.drop_index(
        op.f("ix_scim_provisioning_tokens_revoked_by_id"),
        table_name="scim_provisioning_tokens",
    )
    op.drop_index(
        op.f("ix_scim_provisioning_tokens_profile_id"),
        table_name="scim_provisioning_tokens",
    )
    op.drop_index(
        op.f("ix_scim_provisioning_tokens_organization_id"),
        table_name="scim_provisioning_tokens",
    )
    op.drop_table("scim_provisioning_tokens")

    op.drop_index(
        "ix_scim_provisioning_profiles_org_number",
        table_name="scim_provisioning_profiles",
    )
    op.drop_index(
        op.f("ix_scim_provisioning_profiles_created_by_id"),
        table_name="scim_provisioning_profiles",
    )
    op.drop_index(
        op.f("ix_scim_provisioning_profiles_organization_id"),
        table_name="scim_provisioning_profiles",
    )
    op.drop_table("scim_provisioning_profiles")
