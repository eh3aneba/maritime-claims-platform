"""add WebAuthn authentication assertion custody

Revision ID: 0101_webauthn_authentication
Revises: 0100_webauthn_credentials
"""

from alembic import op
import sqlalchemy as sa

revision = "0101_webauthn_authentication"
down_revision = "0100_webauthn_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webauthn_authentication_transactions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("auth_session_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("challenge_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["auth_session_id"], ["auth_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["webauthn_relying_party_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "challenge_hash",
            name="uq_webauthn_authentication_transactions_challenge_hash",
        ),
    )
    for column in ("organization_id", "user_id", "auth_session_id", "profile_id"):
        op.create_index(
            f"ix_webauthn_authentication_transactions_{column}",
            "webauthn_authentication_transactions",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_webauthn_authentication_transactions_session_open",
        "webauthn_authentication_transactions",
        ["auth_session_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND cancelled_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL AND cancelled_at IS NULL"),
    )
    op.create_index(
        "ix_webauthn_authentication_transactions_org_user_lifecycle",
        "webauthn_authentication_transactions",
        ["organization_id", "user_id", "expires_at", "consumed_at", "cancelled_at"],
        unique=False,
    )

    op.add_column(
        "auth_sessions",
        sa.Column("mfa_webauthn_credential_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_auth_sessions_mfa_webauthn_credential",
        "auth_sessions",
        "webauthn_credentials",
        ["mfa_webauthn_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_auth_sessions_mfa_webauthn_credential_id",
        "auth_sessions",
        ["mfa_webauthn_credential_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_mfa_webauthn_credential_id", table_name="auth_sessions")
    op.drop_constraint(
        "fk_auth_sessions_mfa_webauthn_credential",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_sessions", "mfa_webauthn_credential_id")

    op.drop_index(
        "ix_webauthn_authentication_transactions_org_user_lifecycle",
        table_name="webauthn_authentication_transactions",
    )
    op.drop_index(
        "uq_webauthn_authentication_transactions_session_open",
        table_name="webauthn_authentication_transactions",
    )
    for column in reversed(("organization_id", "user_id", "auth_session_id", "profile_id")):
        op.drop_index(
            f"ix_webauthn_authentication_transactions_{column}",
            table_name="webauthn_authentication_transactions",
        )
    op.drop_table("webauthn_authentication_transactions")
