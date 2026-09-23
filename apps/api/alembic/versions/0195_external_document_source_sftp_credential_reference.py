"""Add governed SFTP credential-reference custody.

Revision ID: 0195_external_doc_source_sftp_cred_ref
Revises: 0194_external_doc_source_sftp_profile
"""

from alembic import op
import sqlalchemy as sa

revision = "0195_external_doc_source_sftp_cred_ref"
down_revision = "0194_external_doc_source_sftp_profile"
branch_labels = None
depends_on = None

BINDING = "external_doc_source_sftp_cred_ref_bindings"
RECEIPT = "external_doc_source_sftp_cred_ref_receipts"


def _safety_columns():
    return [
        sa.Column(
            "credential_reference_stored",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "credential_stored",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "secret_resolution_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "provider_network_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "authentication_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "sftp_session_opened",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "remote_list_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "remote_read_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "remote_write_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "remote_delete_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "evidence_admitted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "document_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "processing_enqueued",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "ai_executed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "claim_mutated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    ]


def _safety_constraints(prefix: str):
    fields = (
        ("credential_stored", "credential"),
        ("secret_resolution_performed", "secret_resolution"),
        ("provider_network_performed", "provider_network"),
        ("authentication_performed", "authentication"),
        ("sftp_session_opened", "session"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint(
            "credential_reference_stored = true",
            name=f"ck_{prefix}_reference_only",
        ),
        *(
            sa.CheckConstraint(
                f"{field} = false",
                name=f"ck_{prefix}_no_{suffix}",
            )
            for field, suffix in fields
        ),
    ]


def upgrade() -> None:
    op.create_table(
        BINDING,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("authentication_kind", sa.String(32), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("reference_namespace", sa.String(128), nullable=False),
        sa.Column("reference_name", sa.String(128), nullable=False),
        sa.Column("reference_version", sa.String(64), nullable=True),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending_second_approval",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["external_document_source_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["terminal_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            name="uq_ext_doc_sftp_cred_ref_profile",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "profile_id",
            "request_key",
            name="uq_ext_doc_sftp_cred_ref_request",
        ),
        sa.CheckConstraint(
            "provider_kind = 'sftp'",
            name="ck_ext_doc_sftp_cred_ref_provider",
        ),
        sa.CheckConstraint(
            "authentication_kind IN ('password','private_key')",
            name="ck_ext_doc_sftp_cred_ref_auth",
        ),
        sa.CheckConstraint(
            "reference_backend IN ('aws_secrets_manager','azure_key_vault','gcp_secret_manager','hashicorp_vault')",
            name="ck_ext_doc_sftp_cred_ref_backend",
        ),
        sa.CheckConstraint(
            "status IN ('pending_second_approval','active','rejected','disabled')",
            name="ck_ext_doc_sftp_cred_ref_status",
        ),
        sa.CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_ext_doc_sftp_cred_ref_four_eyes",
        ),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'active' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'disabled' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_cred_ref_lifecycle",
        ),
        *_safety_constraints("ext_doc_sftp_cred_ref"),
    )
    op.create_index(
        "ix_ext_doc_sftp_cred_ref_org_profile",
        BINDING,
        ["organization_id", "profile_id"],
    )
    op.create_index(
        "ix_ext_doc_sftp_cred_ref_org_status",
        BINDING,
        ["organization_id", "status"],
    )

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("prior_receipt_hash", sa.String(64), nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            [BINDING + ".id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id",
            "sequence_number",
            name="uq_ext_doc_sftp_cred_ref_receipt_seq",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "receipt_hash",
            name="uq_ext_doc_sftp_cred_ref_receipt_hash",
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="ck_ext_doc_sftp_cred_ref_receipt_seq",
        ),
        sa.CheckConstraint(
            "event_type IN ('requested','approved','rejected','disabled')",
            name="ck_ext_doc_sftp_cred_ref_receipt_event",
        ),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval') OR "
            "(event_type = 'approved' AND status_after = 'active') OR "
            "(event_type = 'rejected' AND status_after = 'rejected') OR "
            "(event_type = 'disabled' AND status_after = 'disabled')",
            name="ck_ext_doc_sftp_cred_ref_receipt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_cred_ref_receipt_chain",
        ),
        *_safety_constraints("ext_doc_sftp_cred_ref_receipt"),
    )
    op.create_index(
        "ix_ext_doc_sftp_cred_ref_receipt_binding_seq",
        RECEIPT,
        ["binding_id", "sequence_number"],
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(BINDING)
