"""add server-side authentication session assurance

Revision ID: 0087_auth_session_assurance
Revises: 0086_claim_investigation_plan_activation
"""

from alembic import op
import sqlalchemy as sa

revision = "0087_auth_session_assurance"
down_revision = "0086_claim_investigation_plan_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("identity_source", sa.String(length=50), nullable=False),
        sa.Column("auth_method", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auth_sessions_organization_id"),
        "auth_sessions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_sessions_user_id"),
        "auth_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_sessions_revoked_by_id"),
        "auth_sessions",
        ["revoked_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_org_user",
        "auth_sessions",
        ["organization_id", "user_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_org_lifecycle",
        "auth_sessions",
        ["organization_id", "revoked_at", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_org_lifecycle", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_org_user", table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_revoked_by_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_organization_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
