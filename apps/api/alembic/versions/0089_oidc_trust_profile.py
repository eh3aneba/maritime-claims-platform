"""add governed OIDC trust profile lineage

Revision ID: 0089_oidc_trust_profile
Revises: 0088_external_identity_registry_binding
"""

from alembic import op
import sqlalchemy as sa

revision = "0089_oidc_trust_profile"
down_revision = "0088_external_identity_registry_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_trust_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("issuer_identifier", sa.String(length=500), nullable=False),
        sa.Column("audience", sa.String(length=500), nullable=False),
        sa.Column("jwks_uri", sa.String(length=1000), nullable=False),
        sa.Column("allowed_algorithms", sa.JSON(), nullable=False),
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
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["enterprise_identity_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "profile_number",
            name="uq_oidc_trust_profiles_provider_number",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "profile_hash",
            name="uq_oidc_trust_profiles_provider_hash",
        ),
    )
    op.create_index(
        op.f("ix_oidc_trust_profiles_organization_id"),
        "oidc_trust_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_trust_profiles_provider_id"),
        "oidc_trust_profiles",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_trust_profiles_created_by_id"),
        "oidc_trust_profiles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_oidc_trust_profiles_org_provider_number",
        "oidc_trust_profiles",
        ["organization_id", "provider_id", "profile_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oidc_trust_profiles_org_provider_number",
        table_name="oidc_trust_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_trust_profiles_created_by_id"),
        table_name="oidc_trust_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_trust_profiles_provider_id"),
        table_name="oidc_trust_profiles",
    )
    op.drop_index(
        op.f("ix_oidc_trust_profiles_organization_id"),
        table_name="oidc_trust_profiles",
    )
    op.drop_table("oidc_trust_profiles")
