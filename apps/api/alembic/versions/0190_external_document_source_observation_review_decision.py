"""Add human review decisions and narrow refresh authorizations.

Revision ID: 0190_external_doc_obs_review_decision
Revises: 0189_external_doc_obs_review_handoff
"""

from alembic import op
import sqlalchemy as sa

revision = "0190_external_doc_obs_review_decision"
down_revision = "0189_external_doc_obs_review_handoff"
branch_labels = None
depends_on = None

DECISION = "external_doc_source_observation_review_decisions"
RECEIPT = "external_doc_source_observation_review_decision_receipts"
AUTH = "external_doc_source_observation_refresh_authorizations"


def _safety_columns():
    return [
        sa.Column("handoff_integrity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_authority_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_document_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_decision_recorded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("service_identity_used_as_human", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        ("handoff_integrity_verified", "handoff"),
        ("current_authority_verified", "authority"),
        ("current_document_verified", "document"),
        ("human_decision_recorded", "human"),
    )
    false_fields = (
        ("service_identity_used_as_human", "service_human"),
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
        DECISION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("handoff_id", sa.Uuid(), nullable=False),
        sa.Column("observation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("current_document_file_hash", sa.String(64), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("handoff_completion_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("prior_projection_hash", sa.String(64), nullable=False),
        sa.Column("prior_provider_version_hash", sa.String(64), nullable=True),
        sa.Column("observed_projection_hash", sa.String(64), nullable=True),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("decision_kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handoff_id"], ["external_doc_source_observation_review_handoffs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_execution_id"], ["external_doc_source_due_tick_observation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_id"], ["external_doc_source_recurring_observation_schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("handoff_id", name="uq_ext_doc_obs_review_dec_handoff"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_review_dec_request"),
        sa.CheckConstraint("decision_kind IN ('approve_refresh','dismiss','acknowledge_missing')", name="ck_ext_doc_obs_review_dec_kind"),
        sa.CheckConstraint("status IN ('refresh_authorized','dismissed','missing_acknowledged')", name="ck_ext_doc_obs_review_dec_status"),
        sa.CheckConstraint(
            "(result_status = 'changed' AND decision_kind IN ('approve_refresh','dismiss')) OR "
            "(result_status = 'missing' AND decision_kind IN ('acknowledge_missing','dismiss'))",
            name="ck_ext_doc_obs_review_dec_matrix",
        ),
        sa.CheckConstraint(
            "(decision_kind = 'approve_refresh' AND status = 'refresh_authorized') OR "
            "(decision_kind = 'dismiss' AND status = 'dismissed') OR "
            "(decision_kind = 'acknowledge_missing' AND status = 'missing_acknowledged')",
            name="ck_ext_doc_obs_review_dec_lifecycle",
        ),
        sa.CheckConstraint("current_version_number >= 1", name="ck_ext_doc_obs_review_dec_version"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_review_dec_provider"),
        *_safety_constraints("ext_doc_obs_review_dec"),
    )
    op.create_index("ix_ext_doc_obs_review_dec_org_claim", DECISION, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_obs_review_dec_handoff", DECISION, ["handoff_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("status_after", sa.String(32), nullable=False),
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
        sa.ForeignKeyConstraint(["decision_id"], [DECISION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id", "sequence_number", name="uq_ext_doc_obs_review_dec_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_review_dec_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('approve_refresh','dismiss','acknowledge_missing')", name="ck_ext_doc_obs_review_dec_rcpt_event"),
        sa.CheckConstraint("status_after IN ('refresh_authorized','dismissed','missing_acknowledged')", name="ck_ext_doc_obs_review_dec_rcpt_status"),
        *_safety_constraints("ext_doc_obs_review_dec_rcpt"),
    )

    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("handoff_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("current_document_file_hash", sa.String(64), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("handoff_completion_hash", sa.String(64), nullable=False),
        sa.Column("decision_completion_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("prior_projection_hash", sa.String(64), nullable=False),
        sa.Column("prior_provider_version_hash", sa.String(64), nullable=True),
        sa.Column("observed_projection_hash", sa.String(64), nullable=False),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("execution_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="authorized"),
        sa.Column("authorized_by_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handoff_id"], ["external_doc_source_observation_review_handoffs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_id"], [DECISION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id", name="uq_ext_doc_obs_refresh_auth_decision"),
        sa.UniqueConstraint("handoff_id", name="uq_ext_doc_obs_refresh_auth_handoff"),
        sa.CheckConstraint("status = 'authorized'", name="ck_ext_doc_obs_refresh_auth_status"),
        sa.CheckConstraint("execution_limit = 1", name="ck_ext_doc_obs_refresh_auth_limit"),
        sa.CheckConstraint("result_status = 'changed'", name="ck_ext_doc_obs_refresh_auth_result"),
        sa.CheckConstraint("observed_projection_hash IS NOT NULL", name="ck_ext_doc_obs_refresh_auth_projection"),
        sa.CheckConstraint("current_version_number >= 1", name="ck_ext_doc_obs_refresh_auth_version"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_auth_provider"),
        *_safety_constraints("ext_doc_obs_refresh_auth"),
    )


def downgrade() -> None:
    op.drop_table(AUTH)
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_obs_review_dec_handoff", table_name=DECISION)
    op.drop_index("ix_ext_doc_obs_review_dec_org_claim", table_name=DECISION)
    op.drop_table(DECISION)
