"""add governed TOTP MFA factor and session assurance provenance

Revision ID: 0095_totp_mfa_foundation
Revises: 0094_saml_callback_session
"""

from alembic import op
import sqlalchemy as sa

revision = "0095_totp_mfa_foundation"
down_revision = "0094_saml_callback_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "totp_mfa_factors",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=160), nullable=False),
        sa.Column("account_label", sa.String(length=320), nullable=False),
        sa.Column("algorithm", sa.String(length=16), server_default="SHA1", nullable=False),
        sa.Column("digits", sa.Integer(), server_default="6", nullable=False),
        sa.Column("period_seconds", sa.Integer(), server_default="30", nullable=False),
        sa.Column("secret_ciphertext", sa.String(length=512), nullable=False),
        sa.Column("secret_nonce", sa.String(length=64), nullable=False),
        sa.Column("secret_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accepted_time_step", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=200), nullable=True),
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
            ["revoked_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_totp_mfa_factors_organization_id"),
        "totp_mfa_factors",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_totp_mfa_factors_user_id"),
        "totp_mfa_factors",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_totp_mfa_factors_revoked_by_id"),
        "totp_mfa_factors",
        ["revoked_by_id"],
        unique=False,
    )
    op.create_index(
        "uq_totp_mfa_factors_user_unrevoked",
        "totp_mfa_factors",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_totp_mfa_factors_org_user_lifecycle",
        "totp_mfa_factors",
        ["organization_id", "user_id", "confirmed_at", "revoked_at"],
        unique=False,
    )

    op.add_column(
        "auth_sessions",
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("mfa_method", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("mfa_factor_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_auth_sessions_mfa_factor_id",
        "auth_sessions",
        "totp_mfa_factors",
        ["mfa_factor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_auth_sessions_mfa_factor_id"),
        "auth_sessions",
        ["mfa_factor_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_sessions_mfa_factor_id"), table_name="auth_sessions")
    op.drop_constraint(
        "fk_auth_sessions_mfa_factor_id",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_sessions", "mfa_factor_id")
    op.drop_column("auth_sessions", "mfa_method")
    op.drop_column("auth_sessions", "mfa_verified_at")

    op.drop_index(
        "ix_totp_mfa_factors_org_user_lifecycle",
        table_name="totp_mfa_factors",
    )
    op.drop_index(
        "uq_totp_mfa_factors_user_unrevoked",
        table_name="totp_mfa_factors",
    )
    op.drop_index(
        op.f("ix_totp_mfa_factors_revoked_by_id"),
        table_name="totp_mfa_factors",
    )
    op.drop_index(
        op.f("ix_totp_mfa_factors_user_id"),
        table_name="totp_mfa_factors",
    )
    op.drop_index(
        op.f("ix_totp_mfa_factors_organization_id"),
        table_name="totp_mfa_factors",
    )
    op.drop_table("totp_mfa_factors")
