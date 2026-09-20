"""Add recurring schedule due-tick metadata observation execution.

Revision ID: 0186_external_doc_due_tick_observation
Revises: 0185_external_doc_recurring_observation_schedule
"""

from alembic import op
import sqlalchemy as sa

revision = "0186_external_doc_due_tick_observation"
down_revision = "0185_external_doc_recurring_observation_schedule"
branch_labels = None
depends_on = None

EXEC = "external_doc_source_due_tick_observation_execs"
RECEIPT = "external_doc_source_due_tick_observation_receipts"


def _safety_columns():
    return [
        sa.Column("schedule_authority_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_document_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_lineage_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("due_tick_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exact_item_metadata_read_performed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_advanced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("background_worker_started", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("schedule_authority_verified", "schedule"),
        ("family_binding_verified", "family"),
        ("current_document_verified", "current"),
        ("provider_lineage_verified", "lineage"),
        ("due_tick_verified", "tick"),
        ("provider_client_constructed", "client"),
        ("exact_item_metadata_read_performed", "metadata"),
    )
    false_fields = (
        ("remote_list_performed", "list"),
        ("remote_content_read_performed", "content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("document_mutated", "document"),
        ("evidence_admitted", "evidence"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_worker_started", "worker"),
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
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("provider_lineage_observation_id", sa.Uuid(), nullable=False),
        sa.Column("provider_lineage_checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("schedule_authorization_hash", sa.String(64), nullable=False),
        sa.Column("schedule_revision_number", sa.Integer(), nullable=False),
        sa.Column("cadence_class", sa.String(32), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_projection_hash", sa.String(64), nullable=False),
        sa.Column("baseline_version_token_hash", sa.String(64), nullable=True),
        sa.Column("observation_operation_kind", sa.String(128), nullable=False),
        sa.Column("observation_adapter_kind", sa.String(128), nullable=False),
        sa.Column("endpoint_policy_hash", sa.String(64), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=True),
        sa.Column("observed_display_name_hash", sa.String(64), nullable=True),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("observed_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("observed_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_mime_type_class", sa.String(128), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
        sa.Column("executed_by_id", sa.Uuid(), nullable=False),
        sa.Column("execution_reason", sa.Text(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_id"], ["external_doc_source_recurring_observation_schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_lineage_observation_id"], ["external_doc_source_gen3_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_lineage_checkpoint_id"], ["external_doc_source_checkpoint_gen3_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "due_at", name="uq_ext_doc_due_obs_tick"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_due_obs_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_due_obs_provider"),
        sa.CheckConstraint("current_version_number >= 1", name="ck_ext_doc_due_obs_version"),
        sa.CheckConstraint("schedule_revision_number >= 1", name="ck_ext_doc_due_obs_revision"),
        sa.CheckConstraint("cadence_minutes >= 60", name="ck_ext_doc_due_obs_cadence"),
        sa.CheckConstraint("result_status IN ('unchanged','changed','missing')", name="ck_ext_doc_due_obs_result"),
        sa.CheckConstraint("status = 'completed'", name="ck_ext_doc_due_obs_status"),
        sa.CheckConstraint("observed_byte_size IS NULL OR observed_byte_size >= 0", name="ck_ext_doc_due_obs_size"),
        sa.CheckConstraint(
            "(result_status = 'missing' AND observed_projection_hash IS NULL AND observed_display_name_hash IS NULL) OR "
            "(result_status IN ('unchanged','changed') AND observed_projection_hash IS NOT NULL AND observed_display_name_hash IS NOT NULL)",
            name="ck_ext_doc_due_obs_observed",
        ),
        *_safety_constraints("ext_doc_due_obs"),
    )
    op.create_index("ix_ext_doc_due_obs_org_claim", EXEC, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_due_obs_schedule", EXEC, ["schedule_id", "due_at"])
    op.create_index("ix_ext_doc_due_obs_family", EXEC, ["binding_id", "completed_at"])

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
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_due_obs_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_due_obs_rcpt_seq"),
        sa.CheckConstraint("event_type = 'completed'", name="ck_ext_doc_due_obs_rcpt_event"),
        sa.CheckConstraint("status_after = 'completed'", name="ck_ext_doc_due_obs_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_due_obs_rcpt_prior"),
        *_safety_constraints("ext_doc_due_obs_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_due_obs_family", table_name=EXEC)
    op.drop_index("ix_ext_doc_due_obs_schedule", table_name=EXEC)
    op.drop_index("ix_ext_doc_due_obs_org_claim", table_name=EXEC)
    op.drop_table(EXEC)
