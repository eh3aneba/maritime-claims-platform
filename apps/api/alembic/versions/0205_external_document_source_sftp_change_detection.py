"""Add bounded exact-file SFTP metadata change detection.

Revision ID: 0205_external_doc_source_sftp_change_detection
Revises: 0204_external_doc_source_sftp_checkpoint
"""

from alembic import op
import sqlalchemy as sa

revision = "0205_external_doc_source_sftp_change_detection"
down_revision = "0204_external_doc_source_sftp_checkpoint"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_sftp_change_detections"
RECEIPT = "external_doc_source_sftp_change_detection_receipts"
MAX_SIZE = 9223372036854775807

_FALSE_FIELDS = (
    "credential_stored", "session_stored", "remote_content_transiently_observed",
    "remote_list_performed", "remote_read_performed", "remote_write_performed",
    "remote_rename_performed", "remote_delete_performed", "remote_mkdir_performed",
    "remote_chmod_performed", "remote_chown_performed", "remote_touch_performed",
    "command_executed", "storage_read_performed", "storage_write_performed",
    "storage_delete_performed", "storage_copy_performed", "checkpoint_advanced",
    "subscription_created", "raw_response_stored", "remote_content_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed",
    "content_extracted", "evidence_admitted", "document_created",
    "processing_enqueued", "ai_executed", "claim_mutated",
)


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_checkpoint_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.Column("exact_item_metadata_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("change_detection_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.Column("storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_advanced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_created", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_n{idx}") for idx, field in enumerate(_FALSE_FIELDS)),
        sa.CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host"),
        sa.CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth"),
        sa.CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_sess"),
        sa.CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_close"),
        sa.CheckConstraint("remote_stat_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_stat"),
        sa.CheckConstraint("exact_item_metadata_read_performed = remote_stat_performed", name=f"ck_{prefix}_meta"),
        sa.CheckConstraint("change_detection_completed = remote_stat_performed", name=f"ck_{prefix}_done"),
    ]


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("directory_listing_id", sa.Uuid(), nullable=False),
        sa.Column("listing_entry_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("baseline_entry_hash", sa.String(64), nullable=False),
        sa.Column("baseline_relative_path_hash", sa.String(64), nullable=False),
        sa.Column("baseline_entry_kind", sa.String(16), nullable=False),
        sa.Column("baseline_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("baseline_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_metadata_id_hash", sa.String(64), nullable=True),
        sa.Column("observation_operation_kind", sa.String(128), nullable=False),
        sa.Column("observation_adapter_kind", sa.String(128), nullable=False),
        sa.Column("observation_policy_hash", sa.String(64), nullable=False),
        sa.Column("authentication_method", sa.String(32), nullable=False),
        sa.Column("latency_class", sa.String(24), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=True),
        sa.Column("observed_entry_kind", sa.String(16), nullable=True),
        sa.Column("observed_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("observed_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_metadata_id_hash", sa.String(64), nullable=True),
        sa.Column("changed_dimensions", sa.String(256), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
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
        sa.ForeignKeyConstraint(["checkpoint_id"], ["external_doc_source_sftp_checkpoints.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["directory_listing_id"], ["external_doc_source_sftp_directory_listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_entry_id"], ["external_doc_source_sftp_directory_listing_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_doc_source_sftp_cred_ref_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_id", name="uq_ext_doc_sftp_change_checkpoint"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_change_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_change_provider"),
        sa.CheckConstraint("result_status IN ('unchanged','changed','missing')", name="ck_ext_doc_sftp_change_result"),
        sa.CheckConstraint("baseline_entry_kind = 'file'", name="ck_ext_doc_sftp_change_base_kind"),
        sa.CheckConstraint("observed_entry_kind IS NULL OR observed_entry_kind = 'file'", name="ck_ext_doc_sftp_change_obs_kind"),
        sa.CheckConstraint("authentication_method IN ('password','public_key')", name="ck_ext_doc_sftp_change_auth_method"),
        sa.CheckConstraint("latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_change_latency"),
        sa.CheckConstraint(
            "(result_status = 'changed' AND changed_dimensions IS NOT NULL) OR "
            "(result_status IN ('unchanged','missing') AND changed_dimensions IS NULL)",
            name="ck_ext_doc_sftp_change_dimensions",
        ),
        sa.CheckConstraint(f"baseline_byte_size IS NULL OR (baseline_byte_size >= 0 AND baseline_byte_size <= {MAX_SIZE})", name="ck_ext_doc_sftp_change_base_size"),
        sa.CheckConstraint(f"observed_byte_size IS NULL OR (observed_byte_size >= 0 AND observed_byte_size <= {MAX_SIZE})", name="ck_ext_doc_sftp_change_obs_size"),
        sa.CheckConstraint(
            "secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_stat_performed = true "
            "AND exact_item_metadata_read_performed = true AND change_detection_completed = true",
            name="ck_ext_doc_sftp_change_execution",
        ),
        sa.CheckConstraint(
            "(result_status = 'missing' AND observed_projection_hash IS NULL "
            "AND observed_entry_kind IS NULL AND observed_byte_size IS NULL AND observed_modified_at IS NULL "
            "AND observed_metadata_id_hash IS NULL AND changed_dimensions IS NULL) OR "
            "(result_status IN ('unchanged','changed') AND observed_projection_hash IS NOT NULL "
            "AND observed_entry_kind = 'file')",
            name="ck_ext_doc_sftp_change_observed",
        ),
        sa.CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_change_time"),
        *_safety_constraints("sftp_change"),
    )
    for name, cols in (
        ("ix_ext_doc_sftp_change_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_sftp_change_org_result", ["organization_id", "result_status"]),
        ("ix_ext_doc_sftp_change_checkpoint", ["checkpoint_id"]),
        ("ix_ext_doc_sftp_change_listing", ["directory_listing_id"]),
        ("ix_ext_doc_sftp_change_entry", ["listing_entry_id"]),
        ("ix_ext_doc_sftp_change_requester", ["requested_by_id"]),
    ):
        op.create_index(name, EXECUTION, cols)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["execution_id"], [EXECUTION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_sftp_change_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_change_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_change_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_change_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND ssh_transport_performed = false AND host_key_verification_performed = false "
            "AND host_key_verified = false AND authentication_performed = false "
            "AND authentication_succeeded = false AND sftp_session_opened = false "
            "AND sftp_session_closed = false AND remote_stat_performed = false "
            "AND exact_item_metadata_read_performed = false AND change_detection_completed = false) OR "
            "(event_type = 'completed' AND status_after IN ('unchanged','changed','missing') "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_stat_performed = true "
            "AND exact_item_metadata_read_performed = true AND change_detection_completed = true)",
            name="ck_ext_doc_sftp_change_rcpt_map",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_change_rcpt_chain",
        ),
        *_safety_constraints("sftp_change_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_change_rcpt_seq", RECEIPT, ["execution_id", "sequence_number"])
    op.create_index("ix_ext_doc_sftp_change_rcpt_org", RECEIPT, ["organization_id"])
    op.create_index("ix_ext_doc_sftp_change_rcpt_actor", RECEIPT, ["actor_id"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
