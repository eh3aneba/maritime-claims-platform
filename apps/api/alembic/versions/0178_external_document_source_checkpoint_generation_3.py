"""Add bounded checkpoint-generation-3 advancement.

Revision ID: 0178_external_doc_source_checkpoint_generation_3
Revises: 0177_external_doc_source_successor_versioned_restaging
"""

from alembic import op
import sqlalchemy as sa

revision = "0178_external_doc_source_checkpoint_generation_3"
down_revision = "0177_external_doc_source_successor_versioned_restaging"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_checkpoint_gen3_execs"
RECEIPT = "external_doc_source_checkpoint_gen3_receipts"
KIND = "remote_file_snapshot_successor_v1"


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
        "upstream_successor_versioned_restaging_completed",
    )
    dynamic_fields = (
        "checkpoint_created",
        "checkpoint_advanced",
        "checkpoint_generation_3_advance_completed",
    )
    false_fields = (
        "provider_client_constructed",
        "exact_item_metadata_read_performed",
        "remote_content_transiently_observed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "durable_content_staged",
        "sync_executed",
        "subscription_created",
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
        ("credential_reference_stored", "reference"),
        ("credential_reference_resolution_performed", "resolved"),
        ("activation_authorization_consumed", "activation"),
        ("upstream_token_acquisition_completed", "token"),
        ("upstream_provider_client_health_completed", "health"),
        ("upstream_remote_metadata_listing_completed", "listing"),
        ("upstream_remote_file_content_read_completed", "read_proof"),
        ("upstream_remote_content_staging_completed", "stage"),
        ("upstream_sync_checkpoint_completed", "checkpoint"),
        ("upstream_change_detection_completed", "change"),
        ("upstream_versioned_restaging_completed", "restaging"),
        ("upstream_checkpoint_generation_advance_completed", "gen2_advance"),
        ("upstream_successor_change_detection_completed", "successor_change"),
        ("upstream_successor_versioned_restaging_completed", "successor_restage"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("exact_item_metadata_read_performed", "metadata_read"),
        ("remote_content_transiently_observed", "content_observed"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "provider_write"),
        ("remote_delete_performed", "provider_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("durable_content_staged", "staged"),
        ("sync_executed", "sync"),
        ("subscription_created", "subscription"),
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
        sa.Column("successor_versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_checkpoint_generation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("successor_change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_sync_checkpoint_execution_id", sa.Uuid(), nullable=False),
        sa.Column("change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("listing_execution_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_item_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("predecessor_checkpoint_generation", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("predecessor_checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("predecessor_checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_scope_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_request_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_completion_hash", sa.String(64), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=False),
        sa.Column("candidate_scope_hash", sa.String(64), nullable=False),
        sa.Column("candidate_request_hash", sa.String(64), nullable=False),
        sa.Column("candidate_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("candidate_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_generation", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("media_type_class", sa.String(128), nullable=True),
        sa.Column("version_token_hash", sa.String(64), nullable=True),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("successor_checkpoint_kind", sa.String(64), nullable=False, server_default=KIND),
        sa.Column("successor_checkpoint_generation", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("successor_checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("result_status", sa.String(64), nullable=True),
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
        sa.ForeignKeyConstraint(["successor_versioned_restaging_execution_id"], ["external_doc_source_successor_versioned_restage_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_checkpoint_generation_execution_id"], ["external_doc_source_checkpoint_generation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["successor_change_detection_execution_id"], ["external_doc_source_successor_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["versioned_restaging_execution_id"], ["external_doc_source_versioned_restage_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_sync_checkpoint_execution_id"], ["external_doc_source_sync_checkpoint_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["change_detection_execution_id"], ["external_doc_source_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_execution_id"], ["external_doc_source_remote_metadata_list_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["metadata_item_id"], ["external_doc_source_remote_metadata_list_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("successor_versioned_restaging_execution_id", name="uq_ext_doc_cg3_exec_restage"),
        sa.UniqueConstraint("predecessor_checkpoint_generation_execution_id", name="uq_ext_doc_cg3_exec_predecessor"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_cg3_exec_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_cg3_exec_provider"),
        sa.CheckConstraint("predecessor_checkpoint_generation = 2", name="ck_ext_doc_cg3_exec_pred_gen"),
        sa.CheckConstraint("candidate_generation = 3", name="ck_ext_doc_cg3_exec_candidate_gen"),
        sa.CheckConstraint(f"successor_checkpoint_kind = '{KIND}'", name="ck_ext_doc_cg3_exec_kind"),
        sa.CheckConstraint("successor_checkpoint_generation = 3", name="ck_ext_doc_cg3_exec_generation"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_cg3_exec_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status = 'checkpoint_generation_3_advanced'", name="ck_ext_doc_cg3_exec_result"),
        sa.CheckConstraint("content_byte_count >= 0 AND content_byte_count <= 8388608", name="ck_ext_doc_cg3_exec_size"),
        sa.CheckConstraint(
            "(status = 'requested' AND result_status IS NULL AND completed_at IS NULL AND completion_hash IS NULL AND checkpoint_created = false AND checkpoint_advanced = false AND checkpoint_generation_3_advance_completed = false) OR "
            "(status = 'completed' AND result_status = 'checkpoint_generation_3_advanced' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND checkpoint_created = true AND checkpoint_advanced = true AND checkpoint_generation_3_advance_completed = true)",
            name="ck_ext_doc_cg3_exec_lifecycle",
        ),
        *_safety_constraints("ext_doc_cg3_exec"),
    )
    for name, columns in (
        ("ix_ext_doc_cg3_exec_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_cg3_exec_restage", ["successor_versioned_restaging_execution_id"]),
        ("ix_ext_doc_cg3_exec_pred", ["predecessor_checkpoint_generation_execution_id"]),
        ("ix_ext_doc_cg3_exec_org_status", ["organization_id", "status"]),
        ("ix_ext_doc_cg3_exec_org", ["organization_id"]),
        ("ix_ext_doc_cg3_exec_profile", ["profile_id"]),
        ("ix_ext_doc_cg3_exec_schange", ["successor_change_detection_execution_id"]),
        ("ix_ext_doc_cg3_exec_qrestage", ["versioned_restaging_execution_id"]),
        ("ix_ext_doc_cg3_exec_syncpred", ["predecessor_sync_checkpoint_execution_id"]),
        ("ix_ext_doc_cg3_exec_change", ["change_detection_execution_id"]),
        ("ix_ext_doc_cg3_exec_listing", ["listing_execution_id"]),
        ("ix_ext_doc_cg3_exec_item", ["metadata_item_id"]),
        ("ix_ext_doc_cg3_exec_requester", ["requested_by_id"]),
    ):
        op.create_index(name, EXECUTION, columns, unique=False)

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
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_cg3_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_cg3_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_cg3_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_cg3_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND checkpoint_created = false AND checkpoint_advanced = false AND checkpoint_generation_3_advance_completed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND checkpoint_created = true AND checkpoint_advanced = true AND checkpoint_generation_3_advance_completed = true)",
            name="ck_ext_doc_cg3_rcpt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_cg3_rcpt_chain"),
        *_safety_constraints("ext_doc_cg3_rcpt"),
    )
    for name, columns in (
        ("ix_ext_doc_cg3_rcpt_seq", ["execution_id", "sequence_number"]),
        ("ix_ext_doc_cg3_rcpt_org", ["organization_id"]),
        ("ix_ext_doc_cg3_rcpt_execution", ["execution_id"]),
        ("ix_ext_doc_cg3_rcpt_actor", ["actor_id"]),
    ):
        op.create_index(name, RECEIPT, columns, unique=False)


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
