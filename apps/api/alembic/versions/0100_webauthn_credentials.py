"""add verified WebAuthn credential custody

Revision ID: 0100_webauthn_credentials
Revises: 0099_webauthn_reg_foundation
"""

from alembic import op
import sqlalchemy as sa

revision = "0100_webauthn_credentials"
down_revision = "0099_webauthn_reg_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webauthn_credentials",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_number", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("registration_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id_hash", sa.String(length=64), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.Integer(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("aaguid", sa.String(length=32), nullable=False),
        sa.Column("attestation_format", sa.String(length=20), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["webauthn_relying_party_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["registration_transaction_id"],
            ["webauthn_registration_transactions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "credential_id_hash",
            name="uq_webauthn_credentials_credential_hash",
        ),
        sa.UniqueConstraint(
            "registration_transaction_id",
            name="uq_webauthn_credentials_registration_transaction",
        ),
    )
    for column in (
        "organization_id",
        "user_id",
        "profile_id",
        "registration_transaction_id",
    ):
        op.create_index(
            f"ix_webauthn_credentials_{column}",
            "webauthn_credentials",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_webauthn_credentials_org_user_lifecycle",
        "webauthn_credentials",
        ["organization_id", "user_id", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webauthn_credentials_org_user_lifecycle",
        table_name="webauthn_credentials",
    )
    for column in reversed(
        ("organization_id", "user_id", "profile_id", "registration_transaction_id")
    ):
        op.drop_index(
            f"ix_webauthn_credentials_{column}",
            table_name="webauthn_credentials",
        )
    op.drop_table("webauthn_credentials")
