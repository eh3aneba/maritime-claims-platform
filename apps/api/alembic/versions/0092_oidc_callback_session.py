"""add bound OIDC callback session provenance

Revision ID: 0092_oidc_callback_session
Revises: 0091_oidc_runtime_profile
"""

from alembic import op
import sqlalchemy as sa

revision = "0092_oidc_callback_session"
down_revision = "0091_oidc_runtime_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("external_identity_provider_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("external_identity_binding_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("oidc_authorization_transaction_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_auth_sessions_external_identity_provider_id",
        "auth_sessions",
        "enterprise_identity_providers",
        ["external_identity_provider_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_auth_sessions_external_identity_binding_id",
        "auth_sessions",
        "external_identity_bindings",
        ["external_identity_binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_auth_sessions_oidc_authorization_transaction_id",
        "auth_sessions",
        "oidc_authorization_transactions",
        ["oidc_authorization_transaction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_auth_sessions_external_identity_provider_id"),
        "auth_sessions",
        ["external_identity_provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_sessions_external_identity_binding_id"),
        "auth_sessions",
        ["external_identity_binding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_sessions_oidc_authorization_transaction_id"),
        "auth_sessions",
        ["oidc_authorization_transaction_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_oidc_source",
        "auth_sessions",
        ["external_identity_provider_id", "external_identity_binding_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_auth_sessions_oidc_authorization_transaction",
        "auth_sessions",
        ["oidc_authorization_transaction_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_auth_sessions_oidc_authorization_transaction",
        "auth_sessions",
        type_="unique",
    )
    op.drop_index("ix_auth_sessions_oidc_source", table_name="auth_sessions")
    op.drop_index(
        op.f("ix_auth_sessions_oidc_authorization_transaction_id"),
        table_name="auth_sessions",
    )
    op.drop_index(
        op.f("ix_auth_sessions_external_identity_binding_id"),
        table_name="auth_sessions",
    )
    op.drop_index(
        op.f("ix_auth_sessions_external_identity_provider_id"),
        table_name="auth_sessions",
    )
    op.drop_constraint(
        "fk_auth_sessions_oidc_authorization_transaction_id",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_auth_sessions_external_identity_binding_id",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_auth_sessions_external_identity_provider_id",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_sessions", "oidc_authorization_transaction_id")
    op.drop_column("auth_sessions", "external_identity_binding_id")
    op.drop_column("auth_sessions", "external_identity_provider_id")
