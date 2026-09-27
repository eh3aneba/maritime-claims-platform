"""Add changed-file SFTP successor restaging.

Revision ID: 0206_external_doc_source_sftp_successor_restaging
Revises: 0205_external_doc_source_sftp_change_detection
"""

from alembic import op
import sqlalchemy as sa

revision = "0206_external_doc_source_sftp_successor_restaging"
down_revision = "0205_external_doc_source_sftp_change_detection"
branch_labels = None
depends_on = None

RESTAGING = "external_doc_source_sftp_successor_restaging"
RECEIPT = "external_doc_source_sftp_successor_restaging_receipts"
PURPOSE = "external_sftp_changed_content_quarantine_v1"
MAX_BYTES = 8 * 1024 * 1024

_FALSE_FIELDS = (
    "credential_stored", "session_stored", "raw_response_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed",
    "content_extracted", "remote_list_performed", "remote_stat_performed",
    "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
    "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
    "remote_touch_performed", "command_executed", "storage_delete_performed",
    "storage_copy_performed", "checkpoint_advanced", "evidence_admitted",
    "document_created", "processing_enqueued", "ai_executed", "claim_mutated",
)


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_checkpoint_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_change_detection_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("successor_content_proof_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("secret_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("session_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_reconciliation_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_content_staged", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.Column("storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_advanced", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_n{idx}") for idx, field in enumerate(_FALSE_FIELDS)),
        sa.CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host"),
        sa.CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth"),
        sa.CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_sess"),
        sa.CheckConstraint("remote_read_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_read"),
        sa.CheckConstraint("remote_content_transiently_observed = false OR remote_read_performed = true", name=f"ck_{prefix}_content"),
        sa.CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_close"),
        sa.CheckConstraint("successor_content_proof_completed = false OR remote_read_performed = true", name=f"ck_{prefix}_proof"),
        sa.CheckConstraint("durable_content_staged = false OR storage_reconciliation_performed = true", name=f"ck_{prefix}_stage"),
        sa.CheckConstraint("storage_write_performed = false OR durable_content_staged = true", name=f"ck_{prefix}_write"),
        sa.CheckConstraint("remote_content_stored = false OR durable_content_staged = true", name=f"ck_{prefix}_stored"),
    ]


def upgrade() -> None:
    op.create_table(
        RESTAGING,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("change_detection_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("quarantine_staging_id", sa.Uuid(), nullable=False),
        sa.Column("file_content_proof_id", sa.Uuid(), nullable=False),
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
        sa.Column("checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("predecessor_content_sha256", sa.String(64), nullable=False),
        sa.Column("predecessor_content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("change_scope_hash", sa.String(64), nullable=False),
        sa.Column("change_request_hash", sa.String(64), nullable=False),
        sa.Column("change_completion_hash", sa.String(64), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=False),
        sa.Column("observed_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("listing_entry_hash", sa.String(64), nullable=False),
        sa.Column("read_operation_kind", sa.String(128), nullable=False),
        sa.Column("read_policy_hash", sa.String(64), nullable=False),
        sa.Column("read_adapter_kind", sa.String(128), nullable=False),
        sa.Column("successor_generation", sa.Integer(), nullable=False),
        sa.Column("successor_content_sha256", sa.String(64), nullable=True),
        sa.Column("successor_content_byte_count", sa.BigInteger(), nullable=True),
        sa.Column("successor_content_proof_hash", sa.String(64), nullable=True),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False, server_default=PURPOSE),
        sa.Column("storage_object_key", sa.String(1024), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("stored_etag", sa.String(256), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("result_status", sa.String(40), nullable=True),
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
        sa.ForeignKeyConstraint(["change_detection_id"], ["external_doc_source_sftp_change_detections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checkpoint_id"], ["external_doc_source_sftp_checkpoints.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quarantine_staging_id"], ["external_doc_source_sftp_quarantine_staging.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["file_content_proof_id"], ["external_doc_source_sftp_file_content_proofs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["directory_listing_id"], ["external_doc_source_sftp_directory_listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_entry_id"], ["external_doc_source_sftp_directory_listing_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_activation_id"], ["external_doc_source_sftp_session_activations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_doc_source_sftp_cred_ref_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_detection_id", name="uq_ext_doc_sftp_successor_change"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_successor_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_successor_provider"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_sftp_successor_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status = 'successor_staged_verified'", name="ck_ext_doc_sftp_successor_result"),
        sa.CheckConstraint("successor_generation >= 2", name="ck_ext_doc_sftp_successor_generation"),
        sa.CheckConstraint(f"observed_byte_size >= 0 AND observed_byte_size <= {MAX_BYTES}", name="ck_ext_doc_sftp_successor_observed_size"),
        sa.CheckConstraint(f"successor_content_byte_count IS NULL OR (successor_content_byte_count >= 0 AND successor_content_byte_count <= {MAX_BYTES})", name="ck_ext_doc_sftp_successor_content_size"),
        sa.CheckConstraint(f"storage_purpose = '{PURPOSE}'", name="ck_ext_doc_sftp_successor_purpose"),
        sa.CheckConstraint(
            "successor_content_sha256 IS NULL OR successor_content_sha256 <> predecessor_content_sha256",
            name="ck_ext_doc_sftp_successor_new_digest",
        ),
        sa.CheckConstraint(
            "successor_content_byte_count IS NULL OR successor_content_byte_count = observed_byte_size",
            name="ck_ext_doc_sftp_successor_observed_match",
        ),
        sa.CheckConstraint(
            "(status = 'requested' AND completed_at IS NULL AND completion_hash IS NULL AND result_status IS NULL "
            "AND successor_content_sha256 IS NULL AND successor_content_byte_count IS NULL AND successor_content_proof_hash IS NULL AND stored_etag IS NULL "
            "AND successor_content_proof_completed = false AND secret_resolution_performed = false "
            "AND provider_network_performed = false AND ssh_transport_performed = false "
            "AND host_key_verification_performed = false AND host_key_verified = false "
            "AND authentication_performed = false AND authentication_succeeded = false "
            "AND sftp_session_opened = false AND sftp_session_closed = false "
            "AND remote_content_transiently_observed = false AND remote_read_performed = false "
            "AND storage_write_performed = false AND storage_read_performed = false AND storage_reconciliation_performed = false "
            "AND durable_content_staged = false AND remote_content_stored = false) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL "
            "AND result_status = 'successor_staged_verified' AND successor_content_sha256 IS NOT NULL "
            "AND successor_content_byte_count IS NOT NULL AND successor_content_proof_hash IS NOT NULL "
            "AND successor_content_proof_completed = true "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true AND host_key_verified = true "
            "AND authentication_performed = true AND authentication_succeeded = true "
            "AND sftp_session_opened = true AND sftp_session_closed = true "
            "AND remote_content_transiently_observed = true AND remote_read_performed = true "
            "AND storage_write_performed = true AND storage_read_performed = true AND storage_reconciliation_performed = true "
            "AND durable_content_staged = true AND remote_content_stored = true)",
            name="ck_ext_doc_sftp_successor_lifecycle",
        ),
        *_safety_constraints("sftp_successor"),
    )
    for name, cols in (
        ("ix_ext_doc_sftp_successor_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_sftp_successor_org_status", ["organization_id", "status"]),
        ("ix_ext_doc_sftp_successor_change", ["change_detection_id"]),
        ("ix_ext_doc_sftp_successor_checkpoint", ["checkpoint_id"]),
        ("ix_ext_doc_sftp_successor_requester", ["requested_by_id"]),
    ):
        op.create_index(name, RESTAGING, cols)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("restaging_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["restaging_id"], [RESTAGING + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaging_id", "sequence_number", name="uq_ext_doc_sftp_successor_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_successor_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_successor_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_successor_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND successor_content_proof_completed = false AND remote_read_performed = false "
            "AND storage_write_performed = false AND storage_read_performed = false AND durable_content_staged = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' "
            "AND successor_content_proof_completed = true AND remote_read_performed = true "
            "AND storage_write_performed = true AND storage_read_performed = true AND durable_content_staged = true)",
            name="ck_ext_doc_sftp_successor_rcpt_map",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_successor_rcpt_chain",
        ),
        *_safety_constraints("sftp_successor_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_successor_rcpt_seq", RECEIPT, ["restaging_id", "sequence_number"])
    op.create_index("ix_ext_doc_sftp_successor_rcpt_org", RECEIPT, ["organization_id"])
    op.create_index("ix_ext_doc_sftp_successor_rcpt_actor", RECEIPT, ["actor_id"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(RESTAGING)
