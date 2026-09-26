"""Add bounded read-only SFTP directory metadata listing.

Revision ID: 0201_external_doc_source_sftp_directory_listing
Revises: 0200_external_doc_source_sftp_session_activation
"""

from alembic import op
import sqlalchemy as sa

revision = "0201_external_doc_source_sftp_directory_listing"
down_revision = "0200_external_doc_source_sftp_session_activation"
branch_labels = None
depends_on = None

LISTING = "external_doc_source_sftp_directory_listings"
ENTRY = "external_doc_source_sftp_directory_listing_entries"
RECEIPT = "external_doc_source_sftp_directory_listing_receipts"


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("secret_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ssh_transport_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verification_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authentication_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authentication_succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sftp_session_opened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sftp_session_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_stat_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_rename_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_stored", "credential"),
        ("remote_stat_performed", "stat"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_rename_performed", "rename"),
        ("remote_delete_performed", "delete"),
        ("command_executed", "command"),
        ("checkpoint_created", "checkpoint"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
        sa.CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host_key"),
        sa.CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth_order"),
        sa.CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_session_auth"),
        sa.CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_session_closed"),
        sa.CheckConstraint("remote_list_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_list_session"),
    ]


def upgrade() -> None:
    op.create_table(
        LISTING,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("session_activation_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("session_activation_scope_hash", sa.String(64), nullable=False),
        sa.Column("session_activation_request_hash", sa.String(64), nullable=False),
        sa.Column("session_activation_result_hash", sa.String(64), nullable=False),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("authentication_kind", sa.String(32), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("destination_hostname", sa.String(253), nullable=False),
        sa.Column("destination_port", sa.Integer(), nullable=False),
        sa.Column("pinned_host_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("remote_root_path", sa.String(512), nullable=False),
        sa.Column("remote_root_path_hash", sa.String(64), nullable=False),
        sa.Column("request_relative_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("listing_adapter_kind", sa.String(128), nullable=False),
        sa.Column("listing_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_entries", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("authentication_method", sa.String(32), nullable=True),
        sa.Column("latency_class", sa.String(24), nullable=True),
        sa.Column("entry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("items_hash", sa.String(64), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_activation_id"], ["external_doc_source_sftp_session_activations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_doc_source_sftp_cred_ref_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_activation_id", name="uq_ext_doc_sftp_dir_listing_activation"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_dir_listing_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_dir_listing_provider"),
        sa.CheckConstraint("authentication_kind IN ('password','private_key')", name="ck_ext_doc_sftp_dir_listing_auth_kind"),
        sa.CheckConstraint("listing_limit = 1", name="ck_ext_doc_sftp_dir_listing_limit"),
        sa.CheckConstraint("max_entries = 100", name="ck_ext_doc_sftp_dir_listing_max_entries"),
        sa.CheckConstraint("result_status IN ('listed','failed')", name="ck_ext_doc_sftp_dir_listing_result"),
        sa.CheckConstraint("entry_count >= 0 AND entry_count <= 100", name="ck_ext_doc_sftp_dir_listing_entry_count"),
        sa.CheckConstraint("page_count >= 0 AND page_count <= 1", name="ck_ext_doc_sftp_dir_listing_page_count"),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'credential_resolution_failed','credential_unavailable','connection_failed','connection_timeout',"
            "'host_key_revalidation_failed','authentication_failed','authentication_timeout',"
            "'sftp_subsystem_activation_failed','listing_failed','listing_timeout','path_policy_violation',"
            "'symlink_escape_detected','too_many_entries','oversized_metadata','unsupported_entry_metadata',"
            "'invalid_adapter_result','adapter_error'"
            ")",
            name="ck_ext_doc_sftp_dir_listing_failure",
        ),
        sa.CheckConstraint("authentication_method IS NULL OR authentication_method IN ('password','public_key')", name="ck_ext_doc_sftp_dir_listing_auth_method"),
        sa.CheckConstraint("latency_class IS NULL OR latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_dir_listing_latency"),
        sa.CheckConstraint(
            "(result_status = 'listed' AND failure_code IS NULL AND page_count = 1 AND items_hash IS NOT NULL "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_list_performed = true) OR "
            "(result_status = 'failed' AND failure_code IS NOT NULL AND entry_count = 0 "
            "AND items_hash IS NULL AND truncated = false)",
            name="ck_ext_doc_sftp_dir_listing_outcome",
        ),
        sa.CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_dir_listing_time"),
        *_safety_constraints("ext_doc_sftp_dir_listing"),
    )
    op.create_index("ix_ext_doc_sftp_dir_listing_org_profile", LISTING, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_sftp_dir_listing_org_result", LISTING, ["organization_id", "result_status"])

    op.create_table(
        ENTRY,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("entry_index", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(768), nullable=False),
        sa.Column("entry_name", sa.String(255), nullable=False),
        sa.Column("entry_kind", sa.String(16), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_id_hash", sa.String(64), nullable=True),
        sa.Column("entry_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_id"], [LISTING + ".id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "entry_index", name="uq_ext_doc_sftp_dir_entry_index"),
        sa.UniqueConstraint("listing_id", "entry_hash", name="uq_ext_doc_sftp_dir_entry_hash"),
        sa.CheckConstraint("entry_index >= 0 AND entry_index < 100", name="ck_ext_doc_sftp_dir_entry_index"),
        sa.CheckConstraint("entry_kind IN ('file','directory','symlink','other')", name="ck_ext_doc_sftp_dir_entry_kind"),
        sa.CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_ext_doc_sftp_dir_entry_size"),
    )
    op.create_index("ix_ext_doc_sftp_dir_entry_listing", ENTRY, ["listing_id", "entry_index"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("prior_receipt_hash", sa.String(64), nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_id"], [LISTING + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "sequence_number", name="uq_ext_doc_sftp_dir_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_dir_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_dir_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_dir_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND authentication_performed = false AND sftp_session_opened = false "
            "AND remote_list_performed = false) OR "
            "(event_type = 'completed' AND status_after IN ('listed','failed'))",
            name="ck_ext_doc_sftp_dir_rcpt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_dir_rcpt_chain",
        ),
        *_safety_constraints("ext_doc_sftp_dir_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_dir_rcpt_seq", RECEIPT, ["listing_id", "sequence_number"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(ENTRY)
    op.drop_table(LISTING)
