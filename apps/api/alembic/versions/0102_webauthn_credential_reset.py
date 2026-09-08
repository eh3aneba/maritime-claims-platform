"""add governed WebAuthn credential reset and reenrollment lifecycle

Revision ID: 0102_webauthn_credential_reset
Revises: 0101_webauthn_authentication
"""

from alembic import op
import sqlalchemy as sa

revision = "0102_webauthn_credential_reset"
down_revision = "0101_webauthn_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webauthn_credential_reset_requests",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
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
        sa.Column("reenrollment_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reenrollment_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reenrollment_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("reenrollment_consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reenrollment_credential_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(["credential_id"], ["webauthn_credentials.id"], ondelete="RESTRICT"),
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
        sa.ForeignKeyConstraint(["reenrollment_auth_session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reenrollment_credential_id"], ["webauthn_credentials.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_webauthn_credential_reset_requests_credential_open",
        "webauthn_credential_reset_requests",
        ["credential_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
        sqlite_where=sa.text("status IN ('pending', 'approved')"),
    )
    op.create_index(
        "ix_webauthn_credential_reset_requests_org_lifecycle",
        "webauthn_credential_reset_requests",
        ["organization_id", "user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_webauthn_credential_reset_requests_reenrollment",
        "webauthn_credential_reset_requests",
        ["organization_id", "user_id", "reenrollment_expires_at", "reenrollment_consumed_at"],
        unique=False,
    )
    for column in (
        "organization_id",
        "user_id",
        "credential_id",
        "requested_by_id",
        "requested_auth_session_id",
        "status",
        "approved_by_id",
        "approved_auth_session_id",
        "rejected_by_id",
        "rejected_auth_session_id",
        "cancelled_by_id",
        "cancelled_auth_session_id",
        "executed_by_id",
        "executed_auth_session_id",
        "reenrollment_expires_at",
        "reenrollment_auth_session_id",
        "reenrollment_credential_id",
    ):
        op.create_index(
            f"ix_webauthn_credential_reset_requests_{column}",
            "webauthn_credential_reset_requests",
            [column],
            unique=False,
        )

    op.add_column(
        "webauthn_registration_transactions",
        sa.Column("reenrollment_reset_request_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_webauthn_registration_transactions_reenrollment_reset_request",
        "webauthn_registration_transactions",
        "webauthn_credential_reset_requests",
        ["reenrollment_reset_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_webauthn_registration_transactions_reenrollment_reset_request_id",
        "webauthn_registration_transactions",
        ["reenrollment_reset_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webauthn_registration_transactions_reenrollment_reset_request_id",
        table_name="webauthn_registration_transactions",
    )
    op.drop_constraint(
        "fk_webauthn_registration_transactions_reenrollment_reset_request",
        "webauthn_registration_transactions",
        type_="foreignkey",
    )
    op.drop_column("webauthn_registration_transactions", "reenrollment_reset_request_id")

    for column in reversed(
        (
            "organization_id",
            "user_id",
            "credential_id",
            "requested_by_id",
            "requested_auth_session_id",
            "status",
            "approved_by_id",
            "approved_auth_session_id",
            "rejected_by_id",
            "rejected_auth_session_id",
            "cancelled_by_id",
            "cancelled_auth_session_id",
            "executed_by_id",
            "executed_auth_session_id",
            "reenrollment_expires_at",
            "reenrollment_auth_session_id",
            "reenrollment_credential_id",
        )
    ):
        op.drop_index(
            f"ix_webauthn_credential_reset_requests_{column}",
            table_name="webauthn_credential_reset_requests",
        )
    op.drop_index(
        "ix_webauthn_credential_reset_requests_reenrollment",
        table_name="webauthn_credential_reset_requests",
    )
    op.drop_index(
        "ix_webauthn_credential_reset_requests_org_lifecycle",
        table_name="webauthn_credential_reset_requests",
    )
    op.drop_index(
        "uq_webauthn_credential_reset_requests_credential_open",
        table_name="webauthn_credential_reset_requests",
    )
    op.drop_table("webauthn_credential_reset_requests")
