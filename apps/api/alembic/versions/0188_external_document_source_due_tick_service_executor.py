"""Add internal service-executor due-tick dispatch consumption.

Revision ID: 0188_external_doc_due_tick_service_exec
Revises: 0187_external_doc_due_tick_dispatch
"""

from alembic import op
import sqlalchemy as sa

revision = "0188_external_doc_due_tick_service_exec"
down_revision = "0187_external_doc_due_tick_dispatch"
branch_labels = None
depends_on = None

OBS = "external_doc_source_due_tick_observation_execs"
OBS_RECEIPT = "external_doc_source_due_tick_observation_receipts"
CONSUMPTION = "external_doc_source_due_tick_dispatch_consumptions"
CONSUMPTION_RECEIPT = "external_doc_source_due_tick_dispatch_consumption_receipts"


def _safety_columns():
    return [
        sa.Column("dispatch_integrity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observation_integrity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("service_executor_identity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_observation_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_user_impersonated", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("dispatch_integrity_verified", "dispatch"),
        ("observation_integrity_verified", "observation"),
        ("service_executor_identity_verified", "service_identity"),
        ("metadata_observation_verified", "metadata"),
    )
    false_fields = (
        ("human_user_impersonated", "human_impersonation"),
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
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.add_column(
        OBS,
        sa.Column("actor_kind", sa.String(16), nullable=False, server_default="human"),
    )
    op.add_column(
        OBS,
        sa.Column("service_executor_id_hash", sa.String(64), nullable=True),
    )
    op.alter_column(OBS, "executed_by_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        "ck_ext_doc_due_obs_actor_kind",
        OBS,
        "actor_kind IN ('human','service')",
    )
    op.create_check_constraint(
        "ck_ext_doc_due_obs_actor_identity",
        OBS,
        "(actor_kind = 'human' AND executed_by_id IS NOT NULL AND service_executor_id_hash IS NULL) OR "
        "(actor_kind = 'service' AND executed_by_id IS NULL AND service_executor_id_hash IS NOT NULL)",
    )

    op.add_column(
        OBS_RECEIPT,
        sa.Column("actor_kind", sa.String(16), nullable=False, server_default="human"),
    )
    op.add_column(
        OBS_RECEIPT,
        sa.Column("service_executor_id_hash", sa.String(64), nullable=True),
    )
    op.alter_column(OBS_RECEIPT, "actor_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        "ck_ext_doc_due_obs_rcpt_actor_kind",
        OBS_RECEIPT,
        "actor_kind IN ('human','service')",
    )
    op.create_check_constraint(
        "ck_ext_doc_due_obs_rcpt_actor_identity",
        OBS_RECEIPT,
        "(actor_kind = 'human' AND actor_id IS NOT NULL AND service_executor_id_hash IS NULL) OR "
        "(actor_kind = 'service' AND actor_id IS NULL AND service_executor_id_hash IS NOT NULL)",
    )

    op.create_table(
        CONSUMPTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("observation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("service_executor_id_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dispatch_id"], ["external_doc_source_due_tick_dispatches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_execution_id"], [OBS + ".id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispatch_id", name="uq_ext_doc_due_cons_dispatch"),
        sa.UniqueConstraint("observation_execution_id", name="uq_ext_doc_due_cons_observation"),
        sa.CheckConstraint("status IN ('executed','linked_existing')", name="ck_ext_doc_due_cons_status"),
        *_safety_constraints("ext_doc_due_cons"),
    )
    op.create_index(
        "ix_ext_doc_due_cons_org_dispatch",
        CONSUMPTION,
        ["organization_id", "dispatch_id"],
    )

    op.create_table(
        CONSUMPTION_RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("consumption_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="consumed"),
        sa.Column("status_after", sa.String(24), nullable=False),
        sa.Column("service_executor_id_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["consumption_id"], [CONSUMPTION + ".id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumption_id", "sequence_number", name="uq_ext_doc_due_cons_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_due_cons_rcpt_seq"),
        sa.CheckConstraint("event_type = 'consumed'", name="ck_ext_doc_due_cons_rcpt_event"),
        sa.CheckConstraint("status_after IN ('executed','linked_existing')", name="ck_ext_doc_due_cons_rcpt_status"),
        *_safety_constraints("ext_doc_due_cons_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(CONSUMPTION_RECEIPT)
    op.drop_index("ix_ext_doc_due_cons_org_dispatch", table_name=CONSUMPTION)
    op.drop_table(CONSUMPTION)

    op.drop_constraint("ck_ext_doc_due_obs_rcpt_actor_identity", OBS_RECEIPT, type_="check")
    op.drop_constraint("ck_ext_doc_due_obs_rcpt_actor_kind", OBS_RECEIPT, type_="check")
    op.alter_column(OBS_RECEIPT, "actor_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column(OBS_RECEIPT, "service_executor_id_hash")
    op.drop_column(OBS_RECEIPT, "actor_kind")

    op.drop_constraint("ck_ext_doc_due_obs_actor_identity", OBS, type_="check")
    op.drop_constraint("ck_ext_doc_due_obs_actor_kind", OBS, type_="check")
    op.alter_column(OBS, "executed_by_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column(OBS, "service_executor_id_hash")
    op.drop_column(OBS, "actor_kind")
