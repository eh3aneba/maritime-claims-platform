"""Add DB-only review handoffs for changed/missing due-tick observations.

Revision ID: 0189_external_doc_obs_review_handoff
Revises: 0188_external_doc_due_tick_service_exec
"""

from alembic import op
import sqlalchemy as sa

revision = "0189_external_doc_obs_review_handoff"
down_revision = "0188_external_doc_due_tick_service_exec"
branch_labels = None
depends_on = None

HANDOFF = "external_doc_source_observation_review_handoffs"
RECEIPT = "external_doc_source_observation_review_handoff_receipts"


def _safety_columns():
    return [
        sa.Column("observation_integrity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("eligible_result_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("historical_snapshot_preserved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("projector_identity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_user_impersonated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_acquired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        ("observation_integrity_verified", "observation"),
        ("eligible_result_verified", "eligible"),
        ("historical_snapshot_preserved", "snapshot"),
        ("projector_identity_verified", "projector"),
    )
    false_fields = (
        ("human_user_impersonated", "human_impersonation"),
        ("provider_client_constructed", "client"),
        ("token_acquired", "token"),
        ("remote_list_performed", "list"),
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
        HANDOFF,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("observation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("observed_document_id", sa.Uuid(), nullable=False),
        sa.Column("observed_version_number", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("observation_completion_hash", sa.String(64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=True),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("projector_id_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_execution_id"], ["external_doc_source_due_tick_observation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_id"], ["external_doc_source_recurring_observation_schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_execution_id", name="uq_ext_doc_obs_review_observation"),
        sa.CheckConstraint("result_status IN ('changed','missing')", name="ck_ext_doc_obs_review_result"),
        sa.CheckConstraint("status = 'pending'", name="ck_ext_doc_obs_review_status"),
        sa.CheckConstraint("observed_version_number >= 1", name="ck_ext_doc_obs_review_version"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_review_provider"),
        *_safety_constraints("ext_doc_obs_review"),
    )
    op.create_index("ix_ext_doc_obs_review_org_claim", HANDOFF, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_obs_review_pending", HANDOFF, ["organization_id", "status", "projected_at"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("handoff_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="projected"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("projector_id_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handoff_id"], [HANDOFF + ".id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("handoff_id", "sequence_number", name="uq_ext_doc_obs_review_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_review_rcpt_seq"),
        sa.CheckConstraint("event_type = 'projected'", name="ck_ext_doc_obs_review_rcpt_event"),
        sa.CheckConstraint("status_after = 'pending'", name="ck_ext_doc_obs_review_rcpt_status"),
        *_safety_constraints("ext_doc_obs_review_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_obs_review_pending", table_name=HANDOFF)
    op.drop_index("ix_ext_doc_obs_review_org_claim", table_name=HANDOFF)
    op.drop_table(HANDOFF)
