"""Add recurring exact-item observation schedule authority.

Revision ID: 0185_external_doc_recurring_observation_schedule
Revises: 0184_external_doc_family_version_admission
"""

from alembic import op
import sqlalchemy as sa

revision = "0185_external_doc_recurring_observation_schedule"
down_revision = "0184_external_doc_family_version_admission"
branch_labels = None
depends_on = None

SCHEDULE = "external_doc_source_recurring_observation_schedules"
RECEIPT = "external_doc_source_recurring_observation_schedule_receipts"


def _safety_columns():
    return [
        sa.Column("family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stable_source_identity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_authorization_recorded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("bounded_cadence_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_advanced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("background_worker_started", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("human_authorization_recorded", "human"),
        ("bounded_cadence_verified", "bounded_cadence"),
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
        SCHEDULE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("prior_schedule_id", sa.Uuid(), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("cadence_class", sa.String(32), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("active_binding_guard", sa.Uuid(), nullable=True),
        sa.Column("authorized_by_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_reason", sa.Text(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("disable_request_key", sa.String(128), nullable=True),
        sa.Column("disabled_by_id", sa.Uuid(), nullable=True),
        sa.Column("disable_reason", sa.Text(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_schedule_id"], [SCHEDULE + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["disabled_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "revision_number", name="uq_ext_doc_obs_sched_revision"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_sched_request"),
        sa.UniqueConstraint("organization_id", "profile_id", "disable_request_key", name="uq_ext_doc_obs_sched_disable_request"),
        sa.UniqueConstraint("active_binding_guard", name="uq_ext_doc_obs_sched_active_guard"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_sched_provider"),
        sa.CheckConstraint("revision_number >= 1", name="ck_ext_doc_obs_sched_revision"),
        sa.CheckConstraint(
            "cadence_class IN ('hourly','every_6_hours','every_12_hours','daily')",
            name="ck_ext_doc_obs_sched_cadence",
        ),
        sa.CheckConstraint(
            "(cadence_class = 'hourly' AND cadence_minutes = 60) OR "
            "(cadence_class = 'every_6_hours' AND cadence_minutes = 360) OR "
            "(cadence_class = 'every_12_hours' AND cadence_minutes = 720) OR "
            "(cadence_class = 'daily' AND cadence_minutes = 1440)",
            name="ck_ext_doc_obs_sched_cadence_minutes",
        ),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_ext_doc_obs_sched_status"),
        sa.CheckConstraint(
            "(status = 'active' AND active_binding_guard = binding_id "
            "AND disable_request_key IS NULL AND disabled_by_id IS NULL "
            "AND disable_reason IS NULL AND disabled_at IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'disabled' AND active_binding_guard IS NULL "
            "AND disable_request_key IS NOT NULL AND disabled_by_id IS NOT NULL "
            "AND disable_reason IS NOT NULL AND disabled_at IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_obs_sched_lifecycle",
        ),
        *_safety_constraints("ext_doc_obs_sched"),
    )
    op.create_index("ix_ext_doc_obs_sched_org_claim", SCHEDULE, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_obs_sched_binding", SCHEDULE, ["binding_id"])
    op.create_index("ix_ext_doc_obs_sched_due", SCHEDULE, ["status", "next_due_at"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["schedule_id"], [SCHEDULE + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "sequence_number", name="uq_ext_doc_obs_sched_rcpt_seq"),
        sa.CheckConstraint("sequence_number IN (1,2)", name="ck_ext_doc_obs_sched_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('authorized','disabled')", name="ck_ext_doc_obs_sched_rcpt_event"),
        sa.CheckConstraint("status_after IN ('active','disabled')", name="ck_ext_doc_obs_sched_rcpt_status"),
        sa.CheckConstraint(
            "(sequence_number = 1 AND event_type = 'authorized' AND status_after = 'active' "
            "AND prior_receipt_hash IS NULL) OR "
            "(sequence_number = 2 AND event_type = 'disabled' AND status_after = 'disabled' "
            "AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_obs_sched_rcpt_lifecycle",
        ),
        *_safety_constraints("ext_doc_obs_sched_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_obs_sched_due", table_name=SCHEDULE)
    op.drop_index("ix_ext_doc_obs_sched_binding", table_name=SCHEDULE)
    op.drop_index("ix_ext_doc_obs_sched_org_claim", table_name=SCHEDULE)
    op.drop_table(SCHEDULE)
