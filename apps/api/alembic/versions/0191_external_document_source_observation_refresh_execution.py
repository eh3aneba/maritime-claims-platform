"""Add one-time approved observation refresh executions.

Revision ID: 0191_external_doc_obs_refresh_exec
Revises: 0190_external_doc_obs_review_decision
"""

from alembic import op
import sqlalchemy as sa

revision = "0191_external_doc_obs_refresh_exec"
down_revision = "0190_external_doc_obs_review_decision"
branch_labels = None
depends_on = None

EXEC = "external_doc_source_observation_refresh_execs"
RECEIPT = "external_doc_source_observation_refresh_receipts"


def _safety_columns():
    true_fields = (
        "authorization_integrity_verified",
        "current_authority_verified",
        "current_document_verified",
        "provider_lineage_verified",
        "originating_observation_verified",
        "provider_client_constructed",
        "exact_item_content_read_performed",
        "storage_write_performed",
        "storage_read_performed",
        "durable_content_staged",
    )
    false_fields = (
        "remote_list_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_delete_performed",
        "provider_response_body_stored",
        "remote_content_returned",
        "content_parsed",
        "content_extracted",
        "document_mutated",
        "evidence_admitted",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "checkpoint_advanced",
    )
    return [
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()) for name in true_fields),
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()) for name in false_fields),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("authorization_integrity_verified", "authorization"),
        ("current_authority_verified", "authority"),
        ("current_document_verified", "document"),
        ("provider_lineage_verified", "lineage"),
        ("originating_observation_verified", "observation"),
        ("provider_client_constructed", "client"),
        ("exact_item_content_read_performed", "content_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_read_performed", "storage_read"),
        ("durable_content_staged", "staged"),
    )
    false_fields = (
        ("remote_list_performed", "list"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_delete_performed", "storage_delete"),
        ("provider_response_body_stored", "provider_body"),
        ("remote_content_returned", "content_return"),
        ("content_parsed", "parse"),
        ("content_extracted", "extract"),
        ("document_mutated", "document_mutation"),
        ("evidence_admitted", "evidence"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        EXEC,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("handoff_id", sa.Uuid(), nullable=False),
        sa.Column("observation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("current_document_file_hash", sa.String(64), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("decision_completion_hash", sa.String(64), nullable=False),
        sa.Column("handoff_completion_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=False),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("read_operation_kind", sa.String(128), nullable=False),
        sa.Column("read_adapter_kind", sa.String(128), nullable=False),
        sa.Column("endpoint_policy_hash", sa.String(64), nullable=False),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False),
        sa.Column("storage_object_key", sa.String(512), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("content_media_type_class", sa.String(128), nullable=True),
        sa.Column("content_version_token_hash", sa.String(64), nullable=True),
        sa.Column("content_proof_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
        sa.Column("result_status", sa.String(32), nullable=False, server_default="staged_refresh_verified"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["external_doc_source_observation_refresh_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_id"], ["external_doc_source_observation_review_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handoff_id"], ["external_doc_source_observation_review_handoffs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_execution_id"], ["external_doc_source_due_tick_observation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_ext_doc_obs_refresh_exec_auth"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_refresh_exec_request"),
        sa.CheckConstraint("status = 'completed'", name="ck_ext_doc_obs_refresh_exec_status"),
        sa.CheckConstraint("result_status = 'staged_refresh_verified'", name="ck_ext_doc_obs_refresh_exec_result"),
        sa.CheckConstraint("current_version_number >= 1", name="ck_ext_doc_obs_refresh_exec_version"),
        sa.CheckConstraint("content_byte_count >= 0", name="ck_ext_doc_obs_refresh_exec_size"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_exec_provider"),
        *_safety_constraints("ext_doc_obs_refresh_exec"),
    )
    op.create_index("ix_ext_doc_obs_refresh_exec_org_claim", EXEC, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_obs_refresh_exec_auth", EXEC, ["authorization_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="completed"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="completed"),
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
        sa.ForeignKeyConstraint(["execution_id"], [EXEC + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_obs_refresh_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_refresh_rcpt_seq"),
        sa.CheckConstraint("event_type = 'completed'", name="ck_ext_doc_obs_refresh_rcpt_event"),
        sa.CheckConstraint("status_after = 'completed'", name="ck_ext_doc_obs_refresh_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_obs_refresh_rcpt_prior"),
        *_safety_constraints("ext_doc_obs_refresh_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_obs_refresh_exec_auth", table_name=EXEC)
    op.drop_index("ix_ext_doc_obs_refresh_exec_org_claim", table_name=EXEC)
    op.drop_table(EXEC)
