"""add governed OIDC authorization transaction custody

Revision ID: 0090_oidc_authorization_transaction
Revises: 0089_oidc_trust_profile
"""

from alembic import op
import sqlalchemy as sa

revision = "0090_oidc_authorization_transaction"
down_revision = "0089_oidc_trust_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_authorization_transactions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("trust_profile_id", sa.Uuid(), nullable=False),
        sa.Column("trust_profile_number", sa.Integer(), nullable=False),
        sa.Column("trust_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("pkce_code_challenge", sa.String(length=128), nullable=False),
        sa.Column(
            "pkce_method",
            sa.String(length=10),
            server_default="S256",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            ["trust_profile_id"],
            ["oidc_trust_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "state_hash",
            name="uq_oidc_authorization_transactions_state_hash",
        ),
    )
    op.create_index(
        op.f("ix_oidc_authorization_transactions_organization_id"),
        "oidc_authorization_transactions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_authorization_transactions_provider_id"),
        "oidc_authorization_transactions",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oidc_authorization_transactions_trust_profile_id"),
        "oidc_authorization_transactions",
        ["trust_profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_oidc_authorization_transactions_org_provider_lifecycle",
        "oidc_authorization_transactions",
        ["organization_id", "provider_id", "expires_at", "consumed_at", "cancelled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oidc_authorization_transactions_org_provider_lifecycle",
        table_name="oidc_authorization_transactions",
    )
    op.drop_index(
        op.f("ix_oidc_authorization_transactions_trust_profile_id"),
        table_name="oidc_authorization_transactions",
    )
    op.drop_index(
        op.f("ix_oidc_authorization_transactions_provider_id"),
        table_name="oidc_authorization_transactions",
    )
    op.drop_index(
        op.f("ix_oidc_authorization_transactions_organization_id"),
        table_name="oidc_authorization_transactions",
    )
    op.drop_table("oidc_authorization_transactions")
