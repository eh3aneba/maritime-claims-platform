"""Add governed durable remote-content staging.

Revision ID: 0171_external_doc_source_remote_content_staging
Revises: 0170_external_doc_source_remote_file_content_read
"""

from alembic import op
import sqlalchemy as sa

revision = "0171_external_doc_source_remote_content_staging"
down_revision = "0170_external_doc_source_remote_file_content_read"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_remote_content_stage_execs"
RECEIPT = "external_doc_source_remote_content_stage_receipts"
MAX_BYTES = 8 * 1024 * 1024
PURPOSE = "external_remote_content_quarantine_v1"


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("credential_reference_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("activation_authorization_consumed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_token_acquisition_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_provider_client_health_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_remote_metadata_listing_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("upstream_remote_file_content_read_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_transiently_observed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_content_staged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_authorization_code_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("refresh_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("client_secret_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("private_key_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_client_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_response_body_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_returned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_logged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_parsed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_extracted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_stored", "credential"), ("oauth_authorization_code_stored", "oauth_code"),
        ("access_token_stored", "access_token"), ("refresh_token_stored", "refresh_token"),
        ("id_token_stored", "id_token"), ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"), ("provider_client_stored", "client_stored"),
        ("provider_response_body_stored", "response_body"), ("remote_content_returned", "content_returned"),
        ("remote_content_logged", "content_logged"), ("content_parsed", "parsed"),
        ("content_extracted", "extracted"), ("remote_list_performed", "list"),
        ("remote_write_performed", "write"), ("remote_delete_performed", "delete"),
        ("storage_delete_performed", "storage_delete"), ("subscription_created", "subscription"),
        ("checkpoint_created", "checkpoint"), ("sync_executed", "sync"),
        ("evidence_admitted", "evidence"), ("document_created", "document"), ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        sa.CheckConstraint("credential_reference_resolution_performed = true", name=f"ck_{prefix}_resolved"),
        sa.CheckConstraint("activation_authorization_consumed = true", name=f"ck_{prefix}_consumed"),
        sa.CheckConstraint("upstream_token_acquisition_completed = true", name=f"ck_{prefix}_token_done"),
        sa.CheckConstraint("upstream_provider_client_health_completed = true", name=f"ck_{prefix}_health_done"),
        sa.CheckConstraint("upstream_remote_metadata_listing_completed = true", name=f"ck_{prefix}_listing_done"),
        sa.CheckConstraint("upstream_remote_file_content_read_completed = true", name=f"ck_{prefix}_read_done"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("remote_content_read_execution_id", sa.Uuid(), nullable=False),
        sa.Column("listing_execution_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_item_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("metadata_item_hash", sa.String(64), nullable=False),
        sa.Column("upstream_scope_hash", sa.String(64), nullable=False),
        sa.Column("upstream_request_hash", sa.String(64), nullable=False),
        sa.Column("upstream_completion_hash", sa.String(64), nullable=False),
        sa.Column("read_operation_kind", sa.String(128), nullable=False),
        sa.Column("read_adapter_kind", sa.String(128), nullable=False),
        sa.Column("endpoint_policy_hash", sa.String(64), nullable=False),
        sa.Column("expected_content_sha256", sa.String(64), nullable=False),
        sa.Column("expected_content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("expected_media_type_class", sa.String(128), nullable=True),
        sa.Column("expected_version_token_hash", sa.String(64), nullable=True),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False, server_default=PURPOSE),
        sa.Column("storage_object_key", sa.String(1024), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("stored_etag", sa.String(256), nullable=True),
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
        sa.ForeignKeyConstraint(["remote_content_read_execution_id"], ["external_doc_source_remote_content_read_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_execution_id"], ["external_doc_source_remote_metadata_list_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["metadata_item_id"], ["external_doc_source_remote_metadata_list_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_content_read_execution_id", name="uq_ext_doc_rcs_exec_read"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_rcs_exec_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_rcs_exec_provider"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_rcs_exec_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status = 'staged_verified'", name="ck_ext_doc_rcs_exec_result"),
        sa.CheckConstraint(f"expected_content_byte_count >= 0 AND expected_content_byte_count <= {MAX_BYTES}", name="ck_ext_doc_rcs_exec_size"),
        sa.CheckConstraint(f"storage_purpose = '{PURPOSE}'", name="ck_ext_doc_rcs_exec_purpose"),
        sa.CheckConstraint(
            "(status = 'requested' AND completed_at IS NULL AND completion_hash IS NULL AND result_status IS NULL AND stored_etag IS NULL "
            "AND provider_client_constructed = false AND remote_content_transiently_observed = false AND remote_read_performed = false "
            "AND durable_content_staged = false AND remote_content_stored = false) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND result_status = 'staged_verified' "
            "AND provider_client_constructed = true AND remote_content_transiently_observed = true AND remote_read_performed = true "
            "AND durable_content_staged = true AND remote_content_stored = true)",
            name="ck_ext_doc_rcs_exec_lifecycle",
        ),
        *_safety_constraints("ext_doc_rcs_exec"),
    )
    for name, cols in (
        ("ix_ext_doc_rcs_exec_org_profile", ["organization_id", "profile_id"]),
        ("ix_ext_doc_rcs_exec_org_status", ["organization_id", "status"]),
        ("ix_ext_doc_rcs_exec_org", ["organization_id"]), ("ix_ext_doc_rcs_exec_profile", ["profile_id"]),
        ("ix_ext_doc_rcs_exec_read", ["remote_content_read_execution_id"]),
        ("ix_ext_doc_rcs_exec_listing", ["listing_execution_id"]), ("ix_ext_doc_rcs_exec_item", ["metadata_item_id"]),
        ("ix_ext_doc_rcs_exec_requester", ["requested_by_id"]),
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
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_rcs_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_rcs_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_rcs_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_rcs_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND provider_client_constructed = false "
            "AND remote_content_transiently_observed = false AND remote_read_performed = false AND durable_content_staged = false AND remote_content_stored = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND provider_client_constructed = true "
            "AND remote_content_transiently_observed = true AND remote_read_performed = true AND durable_content_staged = true AND remote_content_stored = true)",
            name="ck_ext_doc_rcs_rcpt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_rcs_rcpt_chain"),
        *_safety_constraints("ext_doc_rcs_rcpt"),
    )
    op.create_index("ix_ext_doc_rcs_rcpt_seq", RECEIPT, ["execution_id", "sequence_number"])
    op.create_index("ix_ext_doc_rcs_rcpt_org", RECEIPT, ["organization_id"])
    op.create_index("ix_ext_doc_rcs_rcpt_exec", RECEIPT, ["execution_id"])
    op.create_index("ix_ext_doc_rcs_rcpt_actor", RECEIPT, ["actor_id"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
