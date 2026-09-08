"""add WebAuthn RP profile and registration challenge custody

Revision ID: 0099_webauthn_registration_foundation
Revises: 0098_mfa_factor_reset_lifecycle
"""

from alembic import op
import sqlalchemy as sa

revision = "0099_webauthn_registration_foundation"
down_revision = "0098_mfa_factor_reset_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webauthn_relying_party_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("rp_id", sa.String(length=253), nullable=False),
        sa.Column("rp_name", sa.String(length=200), nullable=False),
        sa.Column("allowed_origins", sa.JSON(), nullable=False),
        sa.Column("user_verification", sa.String(length=20), nullable=False),
        sa.Column("attestation", sa.String(length=20), nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "profile_number",
            name="uq_webauthn_rp_profiles_org_number",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "profile_hash",
            name="uq_webauthn_rp_profiles_org_hash",
        ),
    )
    op.create_index(
        "ix_webauthn_relying_party_profiles_organization_id",
        "webauthn_relying_party_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_webauthn_relying_party_profiles_created_by_id",
        "webauthn_relying_party_profiles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_webauthn_rp_profiles_org_number",
        "webauthn_relying_party_profiles",
        ["organization_id", "profile_number"],
        unique=False,
    )

    op.create_table(
        "webauthn_registration_transactions",
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
            name="uq_webauthn_registration_transactions_challenge_hash",
        ),
    )
    for column in ("organization_id", "user_id", "auth_session_id", "profile_id"):
        op.create_index(
            f"ix_webauthn_registration_transactions_{column}",
            "webauthn_registration_transactions",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_webauthn_registration_transactions_session_open",
        "webauthn_registration_transactions",
        ["auth_session_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND cancelled_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL AND cancelled_at IS NULL"),
    )
    op.create_index(
        "ix_webauthn_registration_transactions_org_user_lifecycle",
        "webauthn_registration_transactions",
        ["organization_id", "user_id", "expires_at", "consumed_at", "cancelled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webauthn_registration_transactions_org_user_lifecycle",
        table_name="webauthn_registration_transactions",
    )
    op.drop_index(
        "uq_webauthn_registration_transactions_session_open",
        table_name="webauthn_registration_transactions",
    )
    for column in reversed(("organization_id", "user_id", "auth_session_id", "profile_id")):
        op.drop_index(
            f"ix_webauthn_registration_transactions_{column}",
            table_name="webauthn_registration_transactions",
        )
    op.drop_table("webauthn_registration_transactions")
    op.drop_index(
        "ix_webauthn_rp_profiles_org_number",
        table_name="webauthn_relying_party_profiles",
    )
    op.drop_index(
        "ix_webauthn_relying_party_profiles_created_by_id",
        table_name="webauthn_relying_party_profiles",
    )
    op.drop_index(
        "ix_webauthn_relying_party_profiles_organization_id",
        table_name="webauthn_relying_party_profiles",
    )
    op.drop_table("webauthn_relying_party_profiles")
