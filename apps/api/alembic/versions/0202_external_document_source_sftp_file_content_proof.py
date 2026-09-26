"""Add bounded SFTP file content proof.

Revision ID: 0202_external_doc_source_sftp_file_content_proof
Revises: 0201_external_doc_source_sftp_directory_listing
"""

from alembic import op
import sqlalchemy as sa

revision = "0202_external_doc_source_sftp_file_content_proof"
down_revision = "0201_external_doc_source_sftp_directory_listing"
branch_labels = None
depends_on = None

MAX_BYTES = 8 * 1024 * 1024
PROOF = "external_doc_source_sftp_file_content_proofs"
RECEIPT = "external_doc_source_sftp_file_content_proof_receipts"

_FALSE_FIELDS = (
    ("credential_stored", "credential"),
    ("session_stored", "session_stored"),
    ("raw_response_stored", "raw_response"),
    ("remote_content_stored", "content_stored"),
    ("remote_content_returned", "content_returned"),
    ("remote_content_logged", "content_logged"),
    ("content_parsed", "parsed"),
    ("content_extracted", "extracted"),
    ("remote_list_performed", "list"),
    ("remote_stat_performed", "stat"),
    ("remote_write_performed", "write"),
    ("remote_rename_performed", "rename"),
    ("remote_delete_performed", "delete"),
    ("remote_mkdir_performed", "mkdir"),
    ("remote_chmod_performed", "chmod"),
    ("remote_chown_performed", "chown"),
    ("remote_touch_performed", "touch"),
    ("command_executed", "command"),
    ("checkpoint_created", "checkpoint"),
    ("evidence_admitted", "evidence"),
    ("document_created", "document"),
    ("processing_enqueued", "processing"),
    ("ai_executed", "ai"),
    ("claim_mutated", "claim"),
)


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
        sa.Column("remote_content_transiently_observed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("session_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_response_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_returned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_logged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_parsed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_extracted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_stat_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_rename_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_mkdir_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_chmod_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_chown_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_touch_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in _FALSE_FIELDS),
        sa.CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host_key"),
        sa.CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth_order"),
        sa.CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_session_auth"),
        sa.CheckConstraint("remote_read_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_read_session"),
        sa.CheckConstraint("remote_content_transiently_observed = false OR remote_read_performed = true", name=f"ck_{prefix}_content_read"),
        sa.CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_session_closed"),
    ]


def upgrade() -> None:
    op.create_table(
        PROOF,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("directory_listing_id", sa.Uuid(), nullable=False),
        sa.Column("listing_entry_id", sa.Uuid(), nullable=False),
        sa.Column("session_activation_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("authentication_kind", sa.String(32), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("destination_hostname", sa.String(253), nullable=False),
        sa.Column("destination_port", sa.Integer(), nullable=False),
        sa.Column("pinned_host_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("remote_root_path_hash", sa.String(64), nullable=False),
        sa.Column("listing_scope_hash", sa.String(64), nullable=False),
        sa.Column("listing_request_hash", sa.String(64), nullable=False),
        sa.Column("listing_result_hash", sa.String(64), nullable=False),
        sa.Column("listing_items_hash", sa.String(64), nullable=False),
        sa.Column("listing_entry_hash", sa.String(64), nullable=False),
        sa.Column("declared_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("read_adapter_kind", sa.String(128), nullable=False),
        sa.Column("read_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_content_bytes", sa.Integer(), nullable=False, server_default=str(MAX_BYTES)),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("authentication_method", sa.String(32), nullable=False),
        sa.Column("latency_class", sa.String(24), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["directory_listing_id"], ["external_doc_source_sftp_directory_listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_entry_id"], ["external_doc_source_sftp_directory_listing_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_activation_id"], ["external_doc_source_sftp_session_activations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_doc_source_sftp_cred_ref_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_entry_id", name="uq_ext_doc_sftp_content_proof_entry"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_content_proof_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_content_proof_provider"),
        sa.CheckConstraint("authentication_kind IN ('password','private_key')", name="ck_ext_doc_sftp_content_proof_auth_kind"),
        sa.CheckConstraint("authentication_method IN ('password','public_key')", name="ck_ext_doc_sftp_content_proof_auth_method"),
        sa.CheckConstraint("read_limit = 1", name="ck_ext_doc_sftp_content_proof_read_limit"),
        sa.CheckConstraint(f"max_content_bytes = {MAX_BYTES}", name="ck_ext_doc_sftp_content_proof_max_bytes"),
        sa.CheckConstraint("result_status = 'read_verified'", name="ck_ext_doc_sftp_content_proof_result"),
        sa.CheckConstraint(f"declared_byte_size IS NULL OR (declared_byte_size >= 0 AND declared_byte_size <= {MAX_BYTES})", name="ck_ext_doc_sftp_content_proof_declared_size"),
        sa.CheckConstraint(f"content_byte_count >= 0 AND content_byte_count <= {MAX_BYTES}", name="ck_ext_doc_sftp_content_proof_observed_size"),
        sa.CheckConstraint("latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_content_proof_latency"),
        sa.CheckConstraint(
            "secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_content_transiently_observed = true "
            "AND remote_read_performed = true",
            name="ck_ext_doc_sftp_content_proof_success",
        ),
        sa.CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_content_proof_time"),
        *_safety_constraints("ext_doc_sftp_content_proof"),
    )
    op.create_index("ix_ext_doc_sftp_content_proof_org_profile", PROOF, ["organization_id", "profile_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proof_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["proof_id"], [PROOF + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proof_id", "sequence_number", name="uq_ext_doc_sftp_content_proof_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_content_proof_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_content_proof_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_content_proof_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND remote_content_transiently_observed = false AND remote_read_performed = false) OR "
            "(event_type = 'completed' AND status_after = 'read_verified' "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND remote_content_transiently_observed = true AND remote_read_performed = true)",
            name="ck_ext_doc_sftp_content_proof_rcpt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_content_proof_rcpt_chain",
        ),
        *_safety_constraints("ext_doc_sftp_content_proof_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_content_proof_rcpt_seq", RECEIPT, ["proof_id", "sequence_number"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(PROOF)
