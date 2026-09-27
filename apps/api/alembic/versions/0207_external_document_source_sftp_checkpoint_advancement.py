"""Add bounded SFTP successor checkpoint advancement.

Revision ID: 0207_external_doc_source_sftp_checkpoint_advancement
Revises: 0206_external_doc_source_sftp_successor_restaging
"""

from alembic import op
import sqlalchemy as sa

revision = "0207_external_doc_source_sftp_checkpoint_advancement"
down_revision = "0206_external_doc_source_sftp_successor_restaging"
branch_labels = None
depends_on = None

ADVANCEMENT = "external_doc_source_sftp_checkpoint_advancements"
RECEIPT = "external_doc_source_sftp_checkpoint_advancement_receipts"
KIND = "sftp_quarantine_snapshot_successor_v1"
MAX_BYTES = 8 * 1024 * 1024

_FALSE_FIELDS = (
    "secret_resolution_performed", "provider_network_performed", "ssh_transport_performed",
    "host_key_verification_performed", "authentication_performed", "sftp_session_opened",
    "remote_content_transiently_observed", "remote_list_performed", "remote_stat_performed",
    "remote_read_performed", "remote_write_performed", "remote_rename_performed",
    "remote_delete_performed", "remote_mkdir_performed", "remote_chmod_performed",
    "remote_chown_performed", "remote_touch_performed", "command_executed",
    "storage_read_performed", "storage_write_performed", "storage_reconciliation_performed",
    "storage_delete_performed", "storage_copy_performed", "durable_content_staged",
    "credential_stored", "session_stored", "raw_response_stored", "remote_content_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed", "content_extracted",
    "evidence_admitted", "document_created", "processing_enqueued", "ai_executed", "claim_mutated",
)


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_checkpoint_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_change_detection_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_successor_restaging_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.Column("remote_mkdir_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_chmod_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_chown_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_touch_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_reconciliation_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_content_staged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_advanced", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_ref"),
        sa.CheckConstraint("upstream_checkpoint_completed = true", name=f"ck_{prefix}_cp"),
        sa.CheckConstraint("upstream_change_detection_completed = true", name=f"ck_{prefix}_change"),
        sa.CheckConstraint("upstream_successor_restaging_completed = true", name=f"ck_{prefix}_restage"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_n{idx}") for idx, field in enumerate(_FALSE_FIELDS)),
    ]


def upgrade() -> None:
    op.create_table(
        ADVANCEMENT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("successor_restaging_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("change_detection_id", sa.Uuid(), nullable=False),
        sa.Column("quarantine_staging_id", sa.Uuid(), nullable=False),
        sa.Column("file_content_proof_id", sa.Uuid(), nullable=False),
        sa.Column("directory_listing_id", sa.Uuid(), nullable=False),
        sa.Column("listing_entry_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("predecessor_checkpoint_generation", sa.Integer(), nullable=False),
        sa.Column("predecessor_checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("predecessor_checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_scope_hash", sa.String(64), nullable=False),
        sa.Column("candidate_request_hash", sa.String(64), nullable=False),
        sa.Column("candidate_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("candidate_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_generation", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("successor_checkpoint_kind", sa.String(64), nullable=False, server_default=KIND),
        sa.Column("successor_checkpoint_generation", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("successor_checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("result_status", sa.String(32), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["successor_restaging_id"], ["external_doc_source_sftp_successor_restaging.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_checkpoint_id"], ["external_doc_source_sftp_checkpoints.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["change_detection_id"], ["external_doc_source_sftp_change_detections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quarantine_staging_id"], ["external_doc_source_sftp_quarantine_staging.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["file_content_proof_id"], ["external_doc_source_sftp_file_content_proofs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["directory_listing_id"], ["external_doc_source_sftp_directory_listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_entry_id"], ["external_doc_source_sftp_directory_listing_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("successor_restaging_id", name="uq_sftp_cp_adv_restage"),
        sa.UniqueConstraint("predecessor_checkpoint_id", name="uq_sftp_cp_adv_predecessor"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_sftp_cp_adv_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_sftp_cp_adv_provider"),
        sa.CheckConstraint("predecessor_checkpoint_generation = 1", name="ck_sftp_cp_adv_pred_gen"),
        sa.CheckConstraint("successor_checkpoint_generation = 2", name="ck_sftp_cp_adv_succ_gen"),
        sa.CheckConstraint(f"successor_checkpoint_kind = '{KIND}'", name="ck_sftp_cp_adv_kind"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_sftp_cp_adv_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status = 'checkpoint_advanced'", name="ck_sftp_cp_adv_result"),
        sa.CheckConstraint(f"content_byte_count >= 0 AND content_byte_count <= {MAX_BYTES}", name="ck_sftp_cp_adv_size"),
        sa.CheckConstraint(
            "(status = 'requested' AND result_status IS NULL AND completed_at IS NULL AND completion_hash IS NULL "
            "AND checkpoint_created = false AND checkpoint_advanced = false) OR "
            "(status = 'completed' AND result_status = 'checkpoint_advanced' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL "
            "AND checkpoint_created = true AND checkpoint_advanced = true)",
            name="ck_sftp_cp_adv_lifecycle",
        ),
        *_safety_constraints("sftp_cp_adv"),
    )
    for name, cols in (
        ("ix_sftp_cp_adv_org_profile", ["organization_id", "profile_id"]),
        ("ix_sftp_cp_adv_org_status", ["organization_id", "status"]),
        ("ix_sftp_cp_adv_restage", ["successor_restaging_id"]),
        ("ix_sftp_cp_adv_predecessor", ["predecessor_checkpoint_id"]),
        ("ix_sftp_cp_adv_requester", ["requested_by_id"]),
    ):
        op.create_index(name, ADVANCEMENT, cols)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("advancement_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["advancement_id"], [ADVANCEMENT + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("advancement_id", "sequence_number", name="uq_sftp_cp_adv_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_sftp_cp_adv_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_sftp_cp_adv_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_sftp_cp_adv_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND checkpoint_created = false AND checkpoint_advanced = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND checkpoint_created = true AND checkpoint_advanced = true)",
            name="ck_sftp_cp_adv_rcpt_map",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_sftp_cp_adv_rcpt_chain",
        ),
        *_safety_constraints("sftp_cp_adv_rcpt"),
    )
    op.create_index("ix_sftp_cp_adv_rcpt_seq", RECEIPT, ["advancement_id", "sequence_number"])
    op.create_index("ix_sftp_cp_adv_rcpt_org", RECEIPT, ["organization_id"])
    op.create_index("ix_sftp_cp_adv_rcpt_actor", RECEIPT, ["actor_id"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(ADVANCEMENT)
