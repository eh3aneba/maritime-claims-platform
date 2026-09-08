"""add governed MFA factor reset lifecycle

Revision ID: 0098_mfa_factor_reset_lifecycle
Revises: 0097_mfa_recovery_codes
"""

from alembic import op
import sqlalchemy as sa

revision = "0098_mfa_factor_reset_lifecycle"
down_revision = "0097_mfa_recovery_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_factor_reset_requests",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("factor_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_auth_session_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_by_id", sa.Uuid(), nullable=True),
        sa.Column("executed_auth_session_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(["factor_id"], ["totp_mfa_factors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_auth_session_id"], ["auth_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_auth_session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_auth_session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_auth_session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_auth_session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in (
        "organization_id",
        "user_id",
        "factor_id",
        "requested_by_id",
        "requested_auth_session_id",
        "approved_by_id",
        "approved_auth_session_id",
        "rejected_by_id",
        "rejected_auth_session_id",
        "cancelled_by_id",
        "cancelled_auth_session_id",
        "executed_by_id",
        "executed_auth_session_id",
        "status",
    ):
        op.create_index(
            f"ix_mfa_factor_reset_requests_{column}",
            "mfa_factor_reset_requests",
            [column],
            unique=False,
        )

    op.create_index(
        "uq_mfa_factor_reset_requests_factor_open",
        "mfa_factor_reset_requests",
        ["factor_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
        sqlite_where=sa.text("status IN ('pending', 'approved')"),
    )
    op.create_index(
        "ix_mfa_factor_reset_requests_org_lifecycle",
        "mfa_factor_reset_requests",
        ["organization_id", "user_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mfa_factor_reset_requests_org_lifecycle",
        table_name="mfa_factor_reset_requests",
    )
    op.drop_index(
        "uq_mfa_factor_reset_requests_factor_open",
        table_name="mfa_factor_reset_requests",
    )
    for column in reversed(
        (
            "organization_id",
            "user_id",
            "factor_id",
            "requested_by_id",
            "requested_auth_session_id",
            "approved_by_id",
            "approved_auth_session_id",
            "rejected_by_id",
            "rejected_auth_session_id",
            "cancelled_by_id",
            "cancelled_auth_session_id",
            "executed_by_id",
            "executed_auth_session_id",
            "status",
        )
    ):
        op.drop_index(
            f"ix_mfa_factor_reset_requests_{column}",
            table_name="mfa_factor_reset_requests",
        )
    op.drop_table("mfa_factor_reset_requests")
