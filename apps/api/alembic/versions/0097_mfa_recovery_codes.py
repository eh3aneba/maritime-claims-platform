"""add governed MFA recovery codes

Revision ID: 0097_mfa_recovery_codes
Revises: 0096_mfa_policy_enforcement
"""

from alembic import op
import sqlalchemy as sa

revision = "0097_mfa_recovery_codes"
down_revision = "0096_mfa_policy_enforcement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("factor_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by_session_id", sa.Uuid(), nullable=True),
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
            ["factor_id"], ["totp_mfa_factors.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["consumed_auth_session_id"], ["auth_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invalidated_by_session_id"], ["auth_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "factor_id",
            "batch_id",
            "position",
            name="uq_mfa_recovery_codes_factor_batch_position",
        ),
        sa.UniqueConstraint(
            "code_digest",
            name="uq_mfa_recovery_codes_digest",
        ),
    )
    op.create_index(
        "ix_mfa_recovery_codes_organization_id",
        "mfa_recovery_codes",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_mfa_recovery_codes_user_id",
        "mfa_recovery_codes",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_mfa_recovery_codes_factor_id",
        "mfa_recovery_codes",
        ["factor_id"],
        unique=False,
    )
    op.create_index(
        "ix_mfa_recovery_codes_batch_id",
        "mfa_recovery_codes",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_mfa_recovery_codes_consumed_auth_session_id",
        "mfa_recovery_codes",
        ["consumed_auth_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_mfa_recovery_codes_invalidated_by_session_id",
        "mfa_recovery_codes",
        ["invalidated_by_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_mfa_recovery_codes_org_user_lifecycle",
        "mfa_recovery_codes",
        ["organization_id", "user_id", "factor_id", "consumed_at", "invalidated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mfa_recovery_codes_org_user_lifecycle",
        table_name="mfa_recovery_codes",
    )
    op.drop_index(
        "ix_mfa_recovery_codes_invalidated_by_session_id",
        table_name="mfa_recovery_codes",
    )
    op.drop_index(
        "ix_mfa_recovery_codes_consumed_auth_session_id",
        table_name="mfa_recovery_codes",
    )
    op.drop_index("ix_mfa_recovery_codes_batch_id", table_name="mfa_recovery_codes")
    op.drop_index("ix_mfa_recovery_codes_factor_id", table_name="mfa_recovery_codes")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_index(
        "ix_mfa_recovery_codes_organization_id",
        table_name="mfa_recovery_codes",
    )
    op.drop_table("mfa_recovery_codes")
