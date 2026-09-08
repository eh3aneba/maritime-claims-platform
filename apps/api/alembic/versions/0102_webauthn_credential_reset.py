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

_INDEXES = (
    ("ix_wacr_org", "organization_id"),
    ("ix_wacr_user", "user_id"),
    ("ix_wacr_credential", "credential_id"),
    ("ix_wacr_requester", "requested_by_id"),
    ("ix_wacr_request_session", "requested_auth_session_id"),
    ("ix_wacr_status", "status"),
    ("ix_wacr_approver", "approved_by_id"),
    ("ix_wacr_approve_session", "approved_auth_session_id"),
    ("ix_wacr_rejector", "rejected_by_id"),
    ("ix_wacr_reject_session", "rejected_auth_session_id"),
    ("ix_wacr_canceller", "cancelled_by_id"),
    ("ix_wacr_cancel_session", "cancelled_auth_session_id"),
    ("ix_wacr_executor", "executed_by_id"),
    ("ix_wacr_execute_session", "executed_auth_session_id"),
    ("ix_wacr_reenroll_expiry", "reenrollment_expires_at"),
    ("ix_wacr_reenroll_session", "reenrollment_auth_session_id"),
    ("ix_wacr_replacement", "reenrollment_credential_id"),
)


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
        "uq_wacr_credential_open",
        "webauthn_credential_reset_requests",
        ["credential_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
        sqlite_where=sa.text("status IN ('pending', 'approved')"),
    )
    op.create_index(
        "ix_wacr_org_lifecycle",
        "webauthn_credential_reset_requests",
        ["organization_id", "user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_wacr_reenrollment",
        "webauthn_credential_reset_requests",
        ["organization_id", "user_id", "reenrollment_expires_at", "reenrollment_consumed_at"],
        unique=False,
    )
    for index_name, column in _INDEXES:
        op.create_index(
            index_name,
            "webauthn_credential_reset_requests",
            [column],
            unique=False,
        )

    # Deliberately no FK here. Reset -> credential -> registration already forms a durable
    # relational lineage; a reverse FK would introduce a circular metadata dependency.
    # Application services resolve this UUID against the tenant/user/session-bound reset row
    # before permitting any reenrollment bypass.
    op.add_column(
        "webauthn_registration_transactions",
        sa.Column("reenrollment_reset_request_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_wart_reenrollment_reset",
        "webauthn_registration_transactions",
        ["reenrollment_reset_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wart_reenrollment_reset",
        table_name="webauthn_registration_transactions",
    )
    op.drop_column("webauthn_registration_transactions", "reenrollment_reset_request_id")

    for index_name, _column in reversed(_INDEXES):
        op.drop_index(index_name, table_name="webauthn_credential_reset_requests")
    op.drop_index("ix_wacr_reenrollment", table_name="webauthn_credential_reset_requests")
    op.drop_index("ix_wacr_org_lifecycle", table_name="webauthn_credential_reset_requests")
    op.drop_index("uq_wacr_credential_open", table_name="webauthn_credential_reset_requests")
    op.drop_table("webauthn_credential_reset_requests")
