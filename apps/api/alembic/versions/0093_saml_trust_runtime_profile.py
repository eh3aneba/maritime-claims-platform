"""add governed SAML trust/runtime profile lineage

Revision ID: 0093_saml_trust_runtime_profile
Revises: 0092_oidc_callback_session
"""

from alembic import op
import sqlalchemy as sa

revision = "0093_saml_trust_runtime_profile"
down_revision = "0092_oidc_callback_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saml_trust_runtime_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("idp_entity_identifier", sa.String(length=500), nullable=False),
        sa.Column("idp_sso_url", sa.String(length=1000), nullable=False),
        sa.Column("sp_entity_id", sa.String(length=500), nullable=False),
        sa.Column("acs_url", sa.String(length=1000), nullable=False),
        sa.Column("authn_request_binding", sa.String(length=40), nullable=False),
        sa.Column("response_binding", sa.String(length=40), nullable=False),
        sa.Column("allowed_signature_algorithms", sa.JSON(), nullable=False),
        sa.Column("allowed_digest_algorithms", sa.JSON(), nullable=False),
        sa.Column("idp_signing_certificate_pem", sa.Text(), nullable=False),
        sa.Column("certificate_sha256", sa.String(length=64), nullable=False),
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
            name="uq_saml_trust_runtime_profiles_provider_number",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "profile_hash",
            name="uq_saml_trust_runtime_profiles_provider_hash",
        ),
    )
    op.create_index(
        op.f("ix_saml_trust_runtime_profiles_organization_id"),
        "saml_trust_runtime_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saml_trust_runtime_profiles_provider_id"),
        "saml_trust_runtime_profiles",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saml_trust_runtime_profiles_created_by_id"),
        "saml_trust_runtime_profiles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_saml_trust_runtime_profiles_org_provider_number",
        "saml_trust_runtime_profiles",
        ["organization_id", "provider_id", "profile_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saml_trust_runtime_profiles_org_provider_number",
        table_name="saml_trust_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_saml_trust_runtime_profiles_created_by_id"),
        table_name="saml_trust_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_saml_trust_runtime_profiles_provider_id"),
        table_name="saml_trust_runtime_profiles",
    )
    op.drop_index(
        op.f("ix_saml_trust_runtime_profiles_organization_id"),
        table_name="saml_trust_runtime_profiles",
    )
    op.drop_table("saml_trust_runtime_profiles")
