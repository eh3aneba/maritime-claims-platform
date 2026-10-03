"""Add explicit recurring baseline transition for refreshed SFTP Evidence.

Revision ID: 0221_sftp_recurring_baseline_transition
Revises: 0220_sftp_refresh_canonical_admission
"""

from alembic import op
import sqlalchemy as sa

revision = "0221_sftp_recurring_baseline_transition"
down_revision = "0220_sftp_refresh_canonical_admission"
branch_labels = None
depends_on = None

TRANS = "external_doc_source_recurring_baseline_transitions"
RCPT = "external_doc_source_recurring_baseline_transition_receipts"


def upgrade() -> None:
    op.create_table(
        TRANS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_revision_number", sa.Integer(), nullable=False),
        sa.Column("refresh_admission_execution_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_execution_id", sa.Uuid(), nullable=False),
        sa.Column("originating_observation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("prior_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(length=32), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(length=64), nullable=False),
        sa.Column("schedule_authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_admission_completion_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_completion_hash", sa.String(length=64), nullable=False),
        sa.Column("originating_observation_completion_hash", sa.String(length=64), nullable=False),
        sa.Column("baseline_projection_hash", sa.String(length=64), nullable=False),
        sa.Column("baseline_version_token_hash", sa.String(length=64), nullable=True),
        sa.Column("refreshed_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("refreshed_content_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="established"),
        sa.Column("authorized_by_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_reason", sa.Text(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_admission_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("refresh_execution_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("originating_observation_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stable_source_identity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_document_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schedule_authority_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_authorization_recorded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("recurring_baseline_established", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_metadata_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("schedule_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_id"], ["external_doc_source_recurring_observation_schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refresh_admission_execution_id"], ["external_doc_source_observation_refresh_admission_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refresh_execution_id"], ["external_doc_source_observation_refresh_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["originating_observation_execution_id"], ["external_doc_source_due_tick_observation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("refresh_admission_execution_id", name="uq_ext_doc_baseline_trans_admission"),
        sa.UniqueConstraint("current_document_id", name="uq_ext_doc_baseline_trans_document"),
        sa.UniqueConstraint("binding_id", "current_version_number", name="uq_ext_doc_baseline_trans_version"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_baseline_trans_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_baseline_trans_provider"),
        sa.CheckConstraint("current_version_number >= 2", name="ck_ext_doc_baseline_trans_version"),
        sa.CheckConstraint("status = 'established'", name="ck_ext_doc_baseline_trans_status"),
        *[
            sa.CheckConstraint(f"{field} = true", name=f"ck_ext_doc_baseline_trans_{suffix}")
            for field, suffix in (
                ("refresh_admission_verified", "admission"),
                ("refresh_execution_verified", "refresh"),
                ("originating_observation_verified", "observation"),
                ("family_binding_verified", "family"),
                ("stable_source_identity_verified", "source"),
                ("current_document_verified", "current"),
                ("schedule_authority_verified", "schedule"),
                ("human_authorization_recorded", "human"),
                ("recurring_baseline_established", "baseline"),
            )
        ],
        *[
            sa.CheckConstraint(f"{field} = false", name=f"ck_ext_doc_baseline_trans_no_{suffix}")
            for field, suffix in (
                ("provider_client_constructed", "client"),
                ("remote_metadata_read_performed", "metadata"),
                ("remote_content_read_performed", "content"),
                ("storage_read_performed", "storage_read"),
                ("storage_write_performed", "storage_write"),
                ("document_mutated", "document"),
                ("processing_enqueued", "processing"),
                ("ai_executed", "ai"),
                ("claim_mutated", "claim"),
                ("checkpoint_mutated", "checkpoint"),
                ("schedule_mutated", "schedule_mutation"),
            )
        ],
    )
    op.create_index("ix_ext_doc_baseline_trans_binding", TRANS, ["binding_id", "current_version_number"])

    op.create_table(
        RCPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(length=24), nullable=False, server_default="established"),
        sa.Column("status_after", sa.String(length=24), nullable=False, server_default="established"),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_receipt_hash", sa.String(length=64), nullable=True),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_admission_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("refresh_execution_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("originating_observation_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stable_source_identity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_document_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schedule_authority_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_authorization_recorded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("recurring_baseline_established", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_metadata_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("schedule_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_id"], [f"{TRANS}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("transition_id", "sequence_number", name="uq_ext_doc_baseline_trans_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_baseline_trans_rcpt_seq"),
        sa.CheckConstraint("event_type = 'established'", name="ck_ext_doc_baseline_trans_rcpt_event"),
        sa.CheckConstraint("status_after = 'established'", name="ck_ext_doc_baseline_trans_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_baseline_trans_rcpt_prior"),
        *[
            sa.CheckConstraint(f"{field} = true", name=f"ck_ext_doc_baseline_trans_rcpt_{suffix}")
            for field, suffix in (
                ("refresh_admission_verified", "admission"),
                ("refresh_execution_verified", "refresh"),
                ("originating_observation_verified", "observation"),
                ("family_binding_verified", "family"),
                ("stable_source_identity_verified", "source"),
                ("current_document_verified", "current"),
                ("schedule_authority_verified", "schedule"),
                ("human_authorization_recorded", "human"),
                ("recurring_baseline_established", "baseline"),
            )
        ],
        *[
            sa.CheckConstraint(f"{field} = false", name=f"ck_ext_doc_baseline_trans_rcpt_no_{suffix}")
            for field, suffix in (
                ("provider_client_constructed", "client"),
                ("remote_metadata_read_performed", "metadata"),
                ("remote_content_read_performed", "content"),
                ("storage_read_performed", "storage_read"),
                ("storage_write_performed", "storage_write"),
                ("document_mutated", "document"),
                ("processing_enqueued", "processing"),
                ("ai_executed", "ai"),
                ("claim_mutated", "claim"),
                ("checkpoint_mutated", "checkpoint"),
                ("schedule_mutated", "schedule_mutation"),
            )
        ],
    )


def downgrade() -> None:
    op.drop_table(RCPT)
    op.drop_index("ix_ext_doc_baseline_trans_binding", table_name=TRANS)
    op.drop_table(TRANS)
