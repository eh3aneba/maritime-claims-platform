"""add governed SAML MFA assurance equivalence

Revision ID: 0104_saml_mfa_assurance
Revises: 0103_oidc_mfa_assurance
"""

from alembic import op
import sqlalchemy as sa

revision = "0104_saml_mfa_assurance"
down_revision = "0103_oidc_mfa_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saml_mfa_assurance_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("saml_profile_id", sa.Uuid(), nullable=False),
        sa.Column("saml_profile_number", sa.Integer(), nullable=False),
        sa.Column("saml_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("accepted_authn_context_values", sa.JSON(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_profile_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_id"], ["enterprise_identity_providers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["saml_profile_id"], ["saml_trust_runtime_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "profile_number", name="uq_saml_mfa_assurance_provider_number"),
        sa.UniqueConstraint("provider_id", "profile_hash", name="uq_saml_mfa_assurance_provider_hash"),
    )
    op.create_index(
        "ix_saml_mfa_assurance_org_provider_number",
        "saml_mfa_assurance_profiles",
        ["organization_id", "provider_id", "profile_number"],
        unique=False,
    )
    op.create_index("ix_smap_org", "saml_mfa_assurance_profiles", ["organization_id"], unique=False)
    op.create_index("ix_smap_provider", "saml_mfa_assurance_profiles", ["provider_id"], unique=False)
    op.create_index("ix_smap_saml", "saml_mfa_assurance_profiles", ["saml_profile_id"], unique=False)
    op.create_index("ix_smap_creator", "saml_mfa_assurance_profiles", ["created_by_id"], unique=False)

    op.create_table(
        "saml_mfa_assurance_bindings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("saml_profile_id", sa.Uuid(), nullable=False),
        sa.Column("saml_profile_number", sa.Integer(), nullable=False),
        sa.Column("saml_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("assurance_profile_id", sa.Uuid(), nullable=True),
        sa.Column("assurance_profile_number", sa.Integer(), nullable=True),
        sa.Column("assurance_profile_hash", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_type", sa.String(length=20), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_id"], ["enterprise_identity_providers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["saml_authn_transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["saml_profile_id"], ["saml_trust_runtime_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assurance_profile_id"], ["saml_mfa_assurance_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_saml_mfa_assurance_binding_transaction"),
    )
    op.create_index(
        "ix_saml_mfa_assurance_binding_org_provider",
        "saml_mfa_assurance_bindings",
        ["organization_id", "provider_id", "transaction_id"],
        unique=False,
    )
    op.create_index("ix_smab_org", "saml_mfa_assurance_bindings", ["organization_id"], unique=False)
    op.create_index("ix_smab_provider", "saml_mfa_assurance_bindings", ["provider_id"], unique=False)
    op.create_index("ix_smab_txn", "saml_mfa_assurance_bindings", ["transaction_id"], unique=False)
    op.create_index("ix_smab_saml", "saml_mfa_assurance_bindings", ["saml_profile_id"], unique=False)
    op.create_index("ix_smab_profile", "saml_mfa_assurance_bindings", ["assurance_profile_id"], unique=False)


def downgrade() -> None:
    for name in (
        "ix_smab_profile",
        "ix_smab_saml",
        "ix_smab_txn",
        "ix_smab_provider",
        "ix_smab_org",
        "ix_saml_mfa_assurance_binding_org_provider",
    ):
        op.drop_index(name, table_name="saml_mfa_assurance_bindings")
    op.drop_table("saml_mfa_assurance_bindings")

    for name in (
        "ix_smap_creator",
        "ix_smap_saml",
        "ix_smap_provider",
        "ix_smap_org",
        "ix_saml_mfa_assurance_org_provider_number",
    ):
        op.drop_index(name, table_name="saml_mfa_assurance_profiles")
    op.drop_table("saml_mfa_assurance_profiles")
