"""Add governed external document source profiles.

Revision ID: 0158_external_document_source_profiles
Revises: 0157_post_disposal_closure_health
"""

from alembic import op
import sqlalchemy as sa

revision = "0158_external_document_source_profiles"
down_revision = "0157_post_disposal_closure_health"
branch_labels = None
depends_on = None

PROFILE = "external_document_source_profiles"
RECEIPT = "external_document_source_profile_receipts"


def _safety_columns():
    return [
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_token_exchanged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_connection_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    names = {
        "credential_stored": "credential",
        "oauth_token_exchanged": "oauth",
        "remote_list_performed": "list",
        "remote_read_performed": "read",
        "remote_write_performed": "write",
        "remote_delete_performed": "delete",
        "subscription_created": "subscription",
        "sync_executed": "sync",
        "evidence_admitted": "evidence",
        "document_created": "document",
        "claim_mutated": "claim",
        "live_connection_authorized": "live_authority",
    }
    return [sa.CheckConstraint(f"{column} = false", name=f"ck_{prefix}_no_{suffix}") for column, suffix in names.items()]


def upgrade() -> None:
    op.create_table(
        PROFILE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("normalized_config", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_second_approval"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("approval_hash", sa.String(64), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("terminal_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "provider_kind", "config_hash", name="uq_ext_doc_source_scope"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_source_provider"),
        sa.CheckConstraint("status IN ('pending_second_approval','active','rejected','disabled')", name="ck_ext_doc_source_status"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_ext_doc_source_four_eyes"),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'active' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'disabled' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_source_lifecycle",
        ),
        *_safety_constraints("ext_doc_source"),
    )
    op.create_index("ix_ext_doc_source_org_status", PROFILE, ["organization_id", "status"])
    op.create_index("ix_ext_doc_source_org_provider", PROFILE, ["organization_id", "provider_kind"])
    for name, column in (
        ("ix_ext_doc_source_org", "organization_id"),
        ("ix_ext_doc_source_requested", "requested_by_id"),
        ("ix_ext_doc_source_approved", "approved_by_id"),
        ("ix_ext_doc_source_terminal", "terminal_by_id"),
    ):
        op.create_index(name, PROFILE, [column])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("prior_receipt_hash", sa.String(64), nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], [PROFILE + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "sequence_number", name="uq_ext_doc_source_receipt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_source_receipt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_source_receipt_seq"),
        sa.CheckConstraint("event_type IN ('requested','approved','rejected','disabled')", name="ck_ext_doc_source_receipt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval') OR "
            "(event_type = 'approved' AND status_after = 'active') OR "
            "(event_type = 'rejected' AND status_after = 'rejected') OR "
            "(event_type = 'disabled' AND status_after = 'disabled')",
            name="ck_ext_doc_source_receipt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_source_receipt_chain"),
        *_safety_constraints("ext_doc_source_receipt"),
    )
    op.create_index("ix_ext_doc_source_receipt_profile_seq", RECEIPT, ["profile_id", "sequence_number"])
    for name, column in (
        ("ix_ext_doc_source_receipt_org", "organization_id"),
        ("ix_ext_doc_source_receipt_profile", "profile_id"),
        ("ix_ext_doc_source_receipt_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(PROFILE)
