"""add governed OIDC runtime profile lineage

Revision ID: 0091_oidc_runtime_profile
Revises: 0090_oidc_authorization_transaction
"""

from alembic import op
import sqlalchemy as sa

revision = "0091_oidc_runtime_profile"
down_revision = "0090_oidc_authorization_transaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_runtime_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("trust_profile_id", sa.Uuid(), nullable=False),
        sa.Column("trust_profile_number", sa.Integer(), nullable=False),
        sa.Column("trust_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("runtime_profile_number", sa.Integer(), nullable=False),
        sa.Column("authorization_endpoint", sa.String(length=1000), nullable=False),
        sa.Column("token_endpoint", sa.String(length=1000), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1000), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("client_auth_method", sa.String(length=40), nullable=False),
        sa.Column("runtime_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_runtime_profile_hash", sa.String(length=64), nullable=True),
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
            ["provider_id"],
            ["enterprise_identity_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trust_profile_id"], ["oidc_trust_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "runtime_profile_number",
            name="uq_oidc_runtime_profiles_provider_number",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "runtime_profile_hash",
            name="uq_oidc_runtime_profiles_provider_hash",
        ),
    )
    op.create_index(
        op.f("ix_oidc_runtime_profiles_organization_id"),
        "oidc_runtime_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_runtime_profiles_provider_id"),
        "oidc_runtime_profiles",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_runtime_profiles_trust_profile_id"),
        "oidc_runtime_profiles",
        ["trust_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_runtime_profiles_created_by_id"),
        "oidc_runtime_profiles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_oidc_runtime_profiles_org_provider_number",
        "oidc_runtime_profiles",
        ["organization_id", "provider_id", "runtime_profile_number"],
        unique=False,
    )

    op.add_column(
        "oidc_authorization_transactions",
        sa.Column("runtime_profile_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "oidc_authorization_transactions",
        sa.Column("runtime_profile_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "oidc_authorization_transactions",
        sa.Column("runtime_profile_hash", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_oidc_authorization_transactions_runtime_profile_id",
        "oidc_authorization_transactions",
        "oidc_runtime_profiles",
        ["runtime_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_oidc_authorization_transactions_runtime_profile_id"),
        "oidc_authorization_transactions",
        ["runtime_profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_oidc_authorization_transactions_runtime_profile_id"),
        table_name="oidc_authorization_transactions",
    )
    op.drop_constraint(
        "fk_oidc_authorization_transactions_runtime_profile_id",
        "oidc_authorization_transactions",
        type_="foreignkey",
    )
    op.drop_column("oidc_authorization_transactions", "runtime_profile_hash")
    op.drop_column("oidc_authorization_transactions", "runtime_profile_number")
    op.drop_column("oidc_authorization_transactions", "runtime_profile_id")

    op.drop_index(
        "ix_oidc_runtime_profiles_org_provider_number",
        table_name="oidc_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_runtime_profiles_created_by_id"),
        table_name="oidc_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_runtime_profiles_trust_profile_id"),
        table_name="oidc_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_runtime_profiles_provider_id"),
        table_name="oidc_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_runtime_profiles_organization_id"),
        table_name="oidc_runtime_profiles",
    )
    op.drop_table("oidc_runtime_profiles")
