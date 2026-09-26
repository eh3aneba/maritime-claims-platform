"""Add bounded initial SFTP quarantine checkpoint custody.

Revision ID: 0204_external_doc_source_sftp_checkpoint
Revises: 0203_external_doc_source_sftp_quarantine_staging
"""

from alembic import op
import sqlalchemy as sa

revision = "0204_external_doc_source_sftp_checkpoint"
down_revision = "0203_external_doc_source_sftp_quarantine_staging"
branch_labels = None
depends_on = None

CHECKPOINT = "external_doc_source_sftp_checkpoints"
RECEIPT = "external_doc_source_sftp_checkpoint_receipts"
KIND = "initial_sftp_quarantine_snapshot_v1"
GENERATION = 1
MAX_BYTES = 8 * 1024 * 1024

_ALWAYS_FALSE = (
    "secret_resolution_performed", "provider_network_performed", "ssh_transport_performed",
    "host_key_verification_performed", "authentication_performed", "sftp_session_opened",
    "remote_content_transiently_observed", "remote_list_performed", "remote_stat_performed",
    "remote_read_performed", "remote_write_performed", "remote_rename_performed",
    "remote_delete_performed", "command_executed", "storage_read_performed",
    "storage_write_performed", "storage_delete_performed", "storage_copy_performed",
    "sync_executed", "credential_stored", "session_stored", "raw_response_stored",
    "remote_content_stored", "remote_content_returned", "remote_content_logged",
    "content_parsed", "content_extracted", "evidence_admitted", "document_created",
    "processing_enqueued", "ai_executed", "claim_mutated",
)


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_file_content_proof_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_quarantine_staging_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("secret_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ssh_transport_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verification_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authentication_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sftp_session_opened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_transiently_observed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_stat_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_rename_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("session_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_response_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_returned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_logged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_parsed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_extracted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        sa.CheckConstraint("upstream_file_content_proof_completed = true", name=f"ck_{prefix}_proof"),
        sa.CheckConstraint("upstream_quarantine_staging_completed = true", name=f"ck_{prefix}_staging"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{idx}") for idx, field in enumerate(_ALWAYS_FALSE)),
    ]


def upgrade() -> None:
    op.create_table(
        CHECKPOINT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("quarantine_staging_id", sa.Uuid(), nullable=False),
        sa.Column("file_content_proof_id", sa.Uuid(), nullable=False),
        sa.Column("directory_listing_id", sa.Uuid(), nullable=False),
        sa.Column("listing_entry_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("listing_entry_hash", sa.String(64), nullable=False),
        sa.Column("file_content_proof_result_hash", sa.String(64), nullable=False),
        sa.Column("staging_scope_hash", sa.String(64), nullable=False),
        sa.Column("staging_request_hash", sa.String(64), nullable=False),
        sa.Column("staging_completion_hash", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_kind", sa.String(64), nullable=False, server_default=KIND),
        sa.Column("checkpoint_generation", sa.Integer(), nullable=False, server_default=str(GENERATION)),
        sa.Column("checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
        sa.Column("result_status", sa.String(32), nullable=False, server_default="checkpoint_recorded"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quarantine_staging_id"], ["external_doc_source_sftp_quarantine_staging.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["file_content_proof_id"], ["external_doc_source_sftp_file_content_proofs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["directory_listing_id"], ["external_doc_source_sftp_directory_listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_entry_id"], ["external_doc_source_sftp_directory_listing_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quarantine_staging_id", name="uq_ext_doc_sftp_checkpoint_stage"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_checkpoint_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_checkpoint_provider"),
        sa.CheckConstraint("status = 'completed'", name="ck_ext_doc_sftp_checkpoint_status"),
        sa.CheckConstraint("result_status = 'checkpoint_recorded'", name="ck_ext_doc_sftp_checkpoint_result"),
        sa.CheckConstraint(f"checkpoint_kind = '{KIND}'", name="ck_ext_doc_sftp_checkpoint_kind"),
        sa.CheckConstraint(f"checkpoint_generation = {GENERATION}", name="ck_ext_doc_sftp_checkpoint_generation"),
        sa.CheckConstraint(f"content_byte_count >= 0 AND content_byte_count <= {MAX_BYTES}", name="ck_ext_doc_sftp_checkpoint_size"),
        sa.CheckConstraint("checkpoint_created = true", name="ck_ext_doc_sftp_checkpoint_created"),
        sa.CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_checkpoint_time"),
        *_safety_constraints("sftp_checkpoint"),
    )
    for name, cols in (
        ("ix_ext_doc_sftp_checkpoint_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_sftp_checkpoint_stage", ["quarantine_staging_id"]),
        ("ix_ext_doc_sftp_checkpoint_proof", ["file_content_proof_id"]),
        ("ix_ext_doc_sftp_checkpoint_listing", ["directory_listing_id"]),
        ("ix_ext_doc_sftp_checkpoint_entry", ["listing_entry_id"]),
        ("ix_ext_doc_sftp_checkpoint_requester", ["requested_by_id"]),
    ):
        op.create_index(name, CHECKPOINT, cols)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["checkpoint_id"], [CHECKPOINT + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_id", "sequence_number", name="uq_ext_doc_sftp_checkpoint_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_checkpoint_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_checkpoint_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_checkpoint_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND checkpoint_created = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND checkpoint_created = true)",
            name="ck_ext_doc_sftp_checkpoint_rcpt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_checkpoint_rcpt_chain",
        ),
        *_safety_constraints("sftp_checkpoint_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_checkpoint_rcpt_seq", RECEIPT, ["checkpoint_id", "sequence_number"])
    op.create_index("ix_ext_doc_sftp_checkpoint_rcpt_org", RECEIPT, ["organization_id"])
    op.create_index("ix_ext_doc_sftp_checkpoint_rcpt_actor", RECEIPT, ["actor_id"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(CHECKPOINT)
