"""Add DB-only recurring observation due-tick dispatch queue.

Revision ID: 0187_external_doc_due_tick_dispatch
Revises: 0186_external_doc_due_tick_observation
"""

from alembic import op
import sqlalchemy as sa

revision = "0187_external_doc_due_tick_dispatch"
down_revision = "0186_external_doc_due_tick_observation"
branch_labels = None
depends_on = None

DISPATCH = "external_doc_source_due_tick_dispatches"
RECEIPT = "external_doc_source_due_tick_dispatch_receipts"


def _safety_columns():
    return [
        sa.Column("schedule_authority_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_document_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("due_tick_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("internal_worker_identity_recorded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("db_only_dispatch_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_acquired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_metadata_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("schedule_authority_verified", "schedule"),
        ("family_binding_verified", "family"),
        ("current_document_verified", "current"),
        ("due_tick_verified", "tick"),
        ("internal_worker_identity_recorded", "worker"),
        ("db_only_dispatch_verified", "db_only"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("token_acquired", "token"),
        ("remote_metadata_read_performed", "metadata"),
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
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        DISPATCH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("schedule_revision_number", sa.Integer(), nullable=False),
        sa.Column("schedule_authorization_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("cadence_class", sa.String(32), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker_id_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="dispatched"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "due_at", name="uq_ext_doc_due_disp_tick"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_due_disp_provider"),
        sa.CheckConstraint("current_version_number >= 1", name="ck_ext_doc_due_disp_version"),
        sa.CheckConstraint("schedule_revision_number >= 1", name="ck_ext_doc_due_disp_revision"),
        sa.CheckConstraint("cadence_minutes >= 60", name="ck_ext_doc_due_disp_cadence"),
        sa.CheckConstraint("status = 'dispatched'", name="ck_ext_doc_due_disp_status"),
        *_safety_constraints("ext_doc_due_disp"),
    )
    op.create_index("ix_ext_doc_due_disp_due", DISPATCH, ["due_at", "status"])
    op.create_index("ix_ext_doc_due_disp_schedule", DISPATCH, ["schedule_id", "due_at"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="dispatched"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="dispatched"),
        sa.Column("worker_id_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dispatch_id"], [DISPATCH + ".id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispatch_id", "sequence_number", name="uq_ext_doc_due_disp_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_due_disp_rcpt_seq"),
        sa.CheckConstraint("event_type = 'dispatched'", name="ck_ext_doc_due_disp_rcpt_event"),
        sa.CheckConstraint("status_after = 'dispatched'", name="ck_ext_doc_due_disp_rcpt_status"),
        *_safety_constraints("ext_doc_due_disp_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_due_disp_schedule", table_name=DISPATCH)
    op.drop_index("ix_ext_doc_due_disp_due", table_name=DISPATCH)
    op.drop_table(DISPATCH)
