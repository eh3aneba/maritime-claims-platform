"""Add successor generation-3 versioned restaging.

Revision ID: 0177_external_doc_source_successor_versioned_restaging
Revises: 0176_external_doc_source_successor_change_detection
"""

from alembic import op
import sqlalchemy as sa

revision = "0177_external_doc_source_successor_versioned_restaging"
down_revision = "0176_external_doc_source_successor_change_detection"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_successor_versioned_restage_execs"
RECEIPT = "external_doc_source_successor_versioned_restage_receipts"
PURPOSE = "external_remote_content_versioned_quarantine_v1"
GENERATION = 3
MAX_BYTES = 8 * 1024 * 1024


def _safety_columns():
    true_fields = (
        "credential_reference_stored",
        "credential_reference_resolution_performed",
        "activation_authorization_consumed",
        "upstream_token_acquisition_completed",
        "upstream_provider_client_health_completed",
        "upstream_remote_metadata_listing_completed",
        "upstream_remote_file_content_read_completed",
        "upstream_remote_content_staging_completed",
        "upstream_sync_checkpoint_completed",
        "upstream_change_detection_completed",
        "upstream_versioned_restaging_completed",
        "upstream_checkpoint_generation_advance_completed",
        "upstream_successor_change_detection_completed",
    )
    dynamic_fields = (
        "provider_client_constructed",
        "remote_content_transiently_observed",
        "remote_read_performed",
        "storage_read_performed",
        "storage_write_performed",
        "durable_content_staged",
        "remote_content_stored",
        "successor_versioned_restaging_completed",
    )
    false_fields = (
        "credential_stored",
        "oauth_authorization_code_stored",
        "access_token_stored",
        "refresh_token_stored",
        "id_token_stored",
        "client_secret_stored",
        "private_key_stored",
        "provider_client_stored",
        "provider_response_body_stored",
        "remote_content_returned",
        "remote_content_logged",
        "content_parsed",
        "content_extracted",
        "remote_list_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_delete_performed",
        "checkpoint_created",
        "checkpoint_advanced",
        "sync_executed",
        "subscription_created",
        "evidence_admitted",
        "document_created",
        "claim_mutated",
    )
    return [
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()) for name in true_fields),
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()) for name in dynamic_fields),
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()) for name in false_fields),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("credential_reference_stored", "ref"),
        ("credential_reference_resolution_performed", "resolved"),
        ("activation_authorization_consumed", "activation"),
        ("upstream_token_acquisition_completed", "token"),
        ("upstream_provider_client_health_completed", "health"),
        ("upstream_remote_metadata_listing_completed", "listing"),
        ("upstream_remote_file_content_read_completed", "read_proof"),
        ("upstream_remote_content_staging_completed", "stage"),
        ("upstream_sync_checkpoint_completed", "checkpoint"),
        ("upstream_change_detection_completed", "change"),
        ("upstream_versioned_restaging_completed", "restage"),
        ("upstream_checkpoint_generation_advance_completed", "advance"),
        ("upstream_successor_change_detection_completed", "successor_change"),
    )
    false_fields = (
        ("credential_stored", "credential"),
        ("oauth_authorization_code_stored", "oauth_code"),
        ("access_token_stored", "access_token"),
        ("refresh_token_stored", "refresh_token"),
        ("id_token_stored", "id_token"),
        ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"),
        ("provider_client_stored", "client_stored"),
        ("provider_response_body_stored", "response_body"),
        ("remote_content_returned", "content_returned"),
        ("remote_content_logged", "content_logged"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
        ("remote_list_performed", "list"),
        ("remote_write_performed", "provider_write"),
        ("remote_delete_performed", "provider_delete"),
        ("storage_delete_performed", "storage_delete"),
        ("checkpoint_created", "checkpoint_created"),
        ("checkpoint_advanced", "checkpoint_advanced"),
        ("sync_executed", "sync"),
        ("subscription_created", "subscription"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("claim_mutated", "claim"),
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("successor_change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_generation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_sync_checkpoint_execution_id", sa.Uuid(), nullable=False),
        sa.Column("change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("listing_execution_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_item_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_scope_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_request_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_completion_hash", sa.String(64), nullable=False),
        sa.Column("successor_checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("successor_checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=False),
        sa.Column("observed_provider_item_id_hash", sa.String(64), nullable=False),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("observed_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("observed_mime_type_class", sa.String(128), nullable=True),
        sa.Column("read_operation_kind", sa.String(128), nullable=False),
        sa.Column("read_adapter_kind", sa.String(128), nullable=False),
        sa.Column("endpoint_policy_hash", sa.String(64), nullable=False),
        sa.Column("candidate_generation", sa.Integer(), nullable=False, server_default=str(GENERATION)),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False, server_default=PURPOSE),
        sa.Column("storage_object_key", sa.String(1024), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="requested"),
        sa.Column("result_status", sa.String(48), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("content_byte_count", sa.BigInteger(), nullable=True),
        sa.Column("content_media_type_class", sa.String(128), nullable=True),
        sa.Column("content_version_token_hash", sa.String(64), nullable=True),
        sa.Column("content_latency_class", sa.String(24), nullable=True),
        sa.Column("content_proof_hash", sa.String(64), nullable=True),
        sa.Column("content_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stored_etag", sa.String(256), nullable=True),
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
        sa.ForeignKeyConstraint(["successor_change_detection_execution_id"], ["external_doc_source_successor_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checkpoint_generation_execution_id"], ["external_doc_source_checkpoint_generation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["versioned_restaging_execution_id"], ["external_doc_source_versioned_restage_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_sync_checkpoint_execution_id"], ["external_doc_source_sync_checkpoint_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["change_detection_execution_id"], ["external_doc_source_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_execution_id"], ["external_doc_source_remote_metadata_list_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["metadata_item_id"], ["external_doc_source_remote_metadata_list_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("successor_change_detection_execution_id", name="uq_ext_doc_svr3_exec_successor_change"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_svr3_exec_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_svr3_exec_provider"),
        sa.CheckConstraint(f"candidate_generation = {GENERATION}", name="ck_ext_doc_svr3_exec_generation"),
        sa.CheckConstraint(f"storage_purpose = '{PURPOSE}'", name="ck_ext_doc_svr3_exec_purpose"),
        sa.CheckConstraint("status IN ('requested','content_verified','completed')", name="ck_ext_doc_svr3_exec_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status = 'staged_candidate_verified'", name="ck_ext_doc_svr3_exec_result"),
        sa.CheckConstraint(f"content_byte_count IS NULL OR (content_byte_count >= 0 AND content_byte_count <= {MAX_BYTES})", name="ck_ext_doc_svr3_exec_size"),
        sa.CheckConstraint(
            "(status = 'requested' AND content_sha256 IS NULL AND content_byte_count IS NULL AND completed_at IS NULL AND completion_hash IS NULL "
            "AND provider_client_constructed = false AND remote_content_transiently_observed = false AND remote_read_performed = false "
            "AND storage_read_performed = false AND storage_write_performed = false AND durable_content_staged = false AND remote_content_stored = false AND successor_versioned_restaging_completed = false) OR "
            "(status = 'content_verified' AND content_sha256 IS NOT NULL AND content_byte_count IS NOT NULL AND content_verified_at IS NOT NULL "
            "AND completed_at IS NULL AND completion_hash IS NULL AND provider_client_constructed = true AND remote_content_transiently_observed = true "
            "AND remote_read_performed = true AND storage_read_performed = false AND storage_write_performed = false AND durable_content_staged = false "
            "AND remote_content_stored = false AND successor_versioned_restaging_completed = false) OR "
            "(status = 'completed' AND content_sha256 IS NOT NULL AND content_byte_count IS NOT NULL AND content_verified_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND result_status = 'staged_candidate_verified' "
            "AND provider_client_constructed = true AND remote_content_transiently_observed = true AND remote_read_performed = true "
            "AND storage_read_performed = true AND storage_write_performed = true AND durable_content_staged = true AND remote_content_stored = true AND successor_versioned_restaging_completed = true)",
            name="ck_ext_doc_svr3_exec_lifecycle",
        ),
        *_safety_constraints("ext_doc_svr3_exec"),
    )
    for name, columns in (
        ("ix_ext_doc_svr3_exec_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_svr3_exec_successor_change", ["successor_change_detection_execution_id"]),
        ("ix_ext_doc_svr3_exec_org_status", ["organization_id", "status"]),
        ("ix_ext_doc_svr3_exec_org", ["organization_id"]),
        ("ix_ext_doc_svr3_exec_profile", ["profile_id"]),
        ("ix_ext_doc_svr3_exec_checkpoint", ["checkpoint_generation_execution_id"]),
        ("ix_ext_doc_svr3_exec_q", ["versioned_restaging_execution_id"]),
        ("ix_ext_doc_svr3_exec_o", ["predecessor_sync_checkpoint_execution_id"]),
        ("ix_ext_doc_svr3_exec_p", ["change_detection_execution_id"]),
        ("ix_ext_doc_svr3_exec_listing", ["listing_execution_id"]),
        ("ix_ext_doc_svr3_exec_item", ["metadata_item_id"]),
        ("ix_ext_doc_svr3_exec_requester", ["requested_by_id"]),
    ):
        op.create_index(name, EXECUTION, columns, unique=False)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("status_after", sa.String(32), nullable=False),
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
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_svr3_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_svr3_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_svr3_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','content_verified','completed')", name="ck_ext_doc_svr3_rcpt_event"),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_svr3_rcpt_chain"),
        *_safety_constraints("ext_doc_svr3_rcpt"),
    )
    for name, columns in (
        ("ix_ext_doc_svr3_rcpt_seq", ["execution_id", "sequence_number"]),
        ("ix_ext_doc_svr3_rcpt_org", ["organization_id"]),
        ("ix_ext_doc_svr3_rcpt_execution", ["execution_id"]),
        ("ix_ext_doc_svr3_rcpt_actor", ["actor_id"]),
    ):
        op.create_index(name, RECEIPT, columns, unique=False)


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
