"""Add generation-3 successor exact-item change detection.

Revision ID: 0179_external_doc_source_generation_3_change_detection
Revises: 0178_external_doc_source_checkpoint_generation_3
"""

from alembic import op
import sqlalchemy as sa

revision = "0179_external_doc_source_generation_3_change_detection"
down_revision = "0178_external_doc_source_checkpoint_generation_3"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_gen3_change_detect_execs"
RECEIPT = "external_doc_source_gen3_change_detect_receipts"


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
        "upstream_checkpoint_generation_3_advance_completed",
    )
    dynamic_fields = (
        "provider_client_constructed",
        "exact_item_metadata_read_performed",
        "generation_3_successor_change_detection_completed",
    )
    false_fields = (
        "remote_content_transiently_observed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "durable_content_staged",
        "checkpoint_created",
        "checkpoint_advanced",
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
        ("upstream_checkpoint_generation_advance_completed", "gen2"),
        ("upstream_successor_change_detection_completed", "succ_change"),
        ("upstream_successor_versioned_restaging_completed", "succ_restage"),
        ("upstream_checkpoint_generation_3_advance_completed", "gen3"),
    )
    false_fields = (
        ("remote_content_transiently_observed", "content"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("durable_content_staged", "staged"),
        ("checkpoint_created", "checkpoint_create"),
        ("checkpoint_advanced", "checkpoint_advance"),
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
        sa.Column("checkpoint_generation_3_execution_id", sa.Uuid(), nullable=False),
        sa.Column("successor_versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("successor_change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_checkpoint_generation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_sync_checkpoint_execution_id", sa.Uuid(), nullable=False),
        sa.Column("change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("listing_execution_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_item_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("baseline_generation", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("successor_checkpoint_kind", sa.String(64), nullable=False),
        sa.Column("successor_checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("successor_checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("candidate_completion_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_scope_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_request_hash", sa.String(64), nullable=False),
        sa.Column("successor_change_completion_hash", sa.String(64), nullable=False),
        sa.Column("baseline_projection_hash", sa.String(64), nullable=False),
        sa.Column("baseline_provider_item_id_hash", sa.String(64), nullable=False),
        sa.Column("baseline_item_kind", sa.String(16), nullable=False),
        sa.Column("baseline_display_name_hash", sa.String(64), nullable=False),
        sa.Column("baseline_parent_item_id_hash", sa.String(64), nullable=True),
        sa.Column("baseline_version_token_hash", sa.String(64), nullable=True),
        sa.Column("baseline_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("baseline_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_mime_type_class", sa.String(128), nullable=True),
        sa.Column("observation_operation_kind", sa.String(128), nullable=False),
        sa.Column("observation_adapter_kind", sa.String(128), nullable=False),
        sa.Column("endpoint_policy_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("result_status", sa.String(24), nullable=True),
        sa.Column("observed_projection_hash", sa.String(64), nullable=True),
        sa.Column("observed_provider_item_id_hash", sa.String(64), nullable=True),
        sa.Column("observed_item_kind", sa.String(16), nullable=True),
        sa.Column("observed_display_name_hash", sa.String(64), nullable=True),
        sa.Column("observed_parent_item_id_hash", sa.String(64), nullable=True),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("observed_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("observed_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_mime_type_class", sa.String(128), nullable=True),
        sa.Column("changed_dimensions", sa.String(256), nullable=True),
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
        sa.ForeignKeyConstraint(["checkpoint_generation_3_execution_id"], ["external_doc_source_checkpoint_gen3_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["successor_versioned_restaging_execution_id"], ["external_doc_source_successor_versioned_restage_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["successor_change_detection_execution_id"], ["external_doc_source_successor_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_checkpoint_generation_execution_id"], ["external_doc_source_checkpoint_generation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["versioned_restaging_execution_id"], ["external_doc_source_versioned_restage_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_sync_checkpoint_execution_id"], ["external_doc_source_sync_checkpoint_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["change_detection_execution_id"], ["external_doc_source_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_execution_id"], ["external_doc_source_remote_metadata_list_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["metadata_item_id"], ["external_doc_source_remote_metadata_list_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_g3cd_exec_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_g3cd_exec_provider"),
        sa.CheckConstraint("baseline_generation = 3", name="ck_ext_doc_g3cd_exec_generation"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_g3cd_exec_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status IN ('unchanged','changed','missing')", name="ck_ext_doc_g3cd_exec_result"),
        sa.CheckConstraint("baseline_item_kind = 'file'", name="ck_ext_doc_g3cd_exec_base_kind"),
        sa.CheckConstraint("observed_item_kind IS NULL OR observed_item_kind = 'file'", name="ck_ext_doc_g3cd_exec_obs_kind"),
        sa.CheckConstraint("baseline_byte_size IS NULL OR (baseline_byte_size >= 0 AND baseline_byte_size <= 1000000000000000)", name="ck_ext_doc_g3cd_exec_base_size"),
        sa.CheckConstraint("observed_byte_size IS NULL OR (observed_byte_size >= 0 AND observed_byte_size <= 1000000000000000)", name="ck_ext_doc_g3cd_exec_obs_size"),
        sa.CheckConstraint(
            "(status = 'requested' AND result_status IS NULL AND completed_at IS NULL AND completion_hash IS NULL AND observed_projection_hash IS NULL "
            "AND provider_client_constructed = false AND exact_item_metadata_read_performed = false AND generation_3_successor_change_detection_completed = false) OR "
            "(status = 'completed' AND result_status IS NOT NULL AND completed_at IS NOT NULL AND completion_hash IS NOT NULL "
            "AND provider_client_constructed = true AND exact_item_metadata_read_performed = true AND generation_3_successor_change_detection_completed = true)",
            name="ck_ext_doc_g3cd_exec_lifecycle",
        ),
        *_safety_constraints("ext_doc_g3cd_exec"),
    )
    for name, columns in (
        ("ix_ext_doc_g3cd_exec_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_g3cd_exec_checkpoint", ["checkpoint_generation_3_execution_id"]),
        ("ix_ext_doc_g3cd_exec_org_status", ["organization_id", "status"]),
        ("ix_ext_doc_g3cd_exec_org", ["organization_id"]),
        ("ix_ext_doc_g3cd_exec_profile", ["profile_id"]),
        ("ix_ext_doc_g3cd_exec_candidate", ["successor_versioned_restaging_execution_id"]),
        ("ix_ext_doc_g3cd_exec_succ_change", ["successor_change_detection_execution_id"]),
        ("ix_ext_doc_g3cd_exec_pred_gen", ["predecessor_checkpoint_generation_execution_id"]),
        ("ix_ext_doc_g3cd_exec_restage", ["versioned_restaging_execution_id"]),
        ("ix_ext_doc_g3cd_exec_predecessor", ["predecessor_sync_checkpoint_execution_id"]),
        ("ix_ext_doc_g3cd_exec_change", ["change_detection_execution_id"]),
        ("ix_ext_doc_g3cd_exec_listing", ["listing_execution_id"]),
        ("ix_ext_doc_g3cd_exec_item", ["metadata_item_id"]),
        ("ix_ext_doc_g3cd_exec_requester", ["requested_by_id"]),
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
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_g3cd_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_g3cd_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_g3cd_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_g3cd_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND provider_client_constructed = false "
            "AND exact_item_metadata_read_performed = false AND generation_3_successor_change_detection_completed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND provider_client_constructed = true "
            "AND exact_item_metadata_read_performed = true AND generation_3_successor_change_detection_completed = true)",
            name="ck_ext_doc_g3cd_rcpt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_g3cd_rcpt_chain"),
        *_safety_constraints("ext_doc_g3cd_rcpt"),
    )
    op.create_index("ix_ext_doc_g3cd_rcpt_exec", RECEIPT, ["execution_id", "sequence_number"], unique=False)
    op.create_index("ix_ext_doc_g3cd_rcpt_org", RECEIPT, ["organization_id"], unique=False)
    op.create_index("ix_ext_doc_g3cd_rcpt_actor", RECEIPT, ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
