"""add governed SAML callback transaction and session provenance

Revision ID: 0094_saml_callback_session
Revises: 0093_saml_trust_runtime_profile
"""

from alembic import op
import sqlalchemy as sa

revision = "0094_saml_callback_session"
down_revision = "0093_saml_trust_runtime_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saml_authn_transactions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("request_id_hash", sa.String(length=64), nullable=False),
        sa.Column("relay_state_hash", sa.String(length=64), nullable=False),
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
            ["profile_id"],
            ["saml_trust_runtime_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id_hash",
            name="uq_saml_authn_transactions_request_id_hash",
        ),
        sa.UniqueConstraint(
            "relay_state_hash",
            name="uq_saml_authn_transactions_relay_state_hash",
        ),
    )
    op.create_index(
        op.f("ix_saml_authn_transactions_organization_id"),
        "saml_authn_transactions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saml_authn_transactions_provider_id"),
        "saml_authn_transactions",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saml_authn_transactions_profile_id"),
        "saml_authn_transactions",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_saml_authn_transactions_org_provider_lifecycle",
        "saml_authn_transactions",
        ["organization_id", "provider_id", "expires_at", "consumed_at", "cancelled_at"],
        unique=False,
    )

    op.add_column(
        "auth_sessions",
        sa.Column("saml_authn_transaction_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_auth_sessions_saml_authn_transaction_id",
        "auth_sessions",
        "saml_authn_transactions",
        ["saml_authn_transaction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_auth_sessions_saml_authn_transaction_id"),
        "auth_sessions",
        ["saml_authn_transaction_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_auth_sessions_saml_authn_transaction",
        "auth_sessions",
        ["saml_authn_transaction_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_auth_sessions_saml_authn_transaction",
        "auth_sessions",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_auth_sessions_saml_authn_transaction_id"),
        table_name="auth_sessions",
    )
    op.drop_constraint(
        "fk_auth_sessions_saml_authn_transaction_id",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_sessions", "saml_authn_transaction_id")

    op.drop_index(
        "ix_saml_authn_transactions_org_provider_lifecycle",
        table_name="saml_authn_transactions",
    )
    op.drop_index(
        op.f("ix_saml_authn_transactions_profile_id"),
        table_name="saml_authn_transactions",
    )
    op.drop_index(
        op.f("ix_saml_authn_transactions_provider_id"),
        table_name="saml_authn_transactions",
    )
    op.drop_index(
        op.f("ix_saml_authn_transactions_organization_id"),
        table_name="saml_authn_transactions",
    )
    op.drop_table("saml_authn_transactions")
