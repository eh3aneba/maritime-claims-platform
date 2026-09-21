"""Add observation refresh admission authorizations.

Revision ID: 0192_external_doc_obs_refresh_adm_auth
Revises: 0191_external_doc_obs_refresh_exec
"""

from alembic import op
import sqlalchemy as sa

revision = "0192_external_doc_obs_refresh_adm_auth"
down_revision = "0191_external_doc_obs_refresh_exec"
branch_labels = None
depends_on = None

AUTH = "external_doc_source_observation_refresh_admission_auths"
RECEIPT = "external_doc_source_observation_refresh_admission_auth_receipts"


def _safety_columns():
    true_fields = (
        "refresh_execution_verified",
        "durable_family_binding_verified",
        "stable_source_identity_verified",
        "current_document_verified",
        "staged_content_proof_verified",
        "human_authorization_recorded",
    )
    false_fields = (
        "provider_client_constructed",
        "oauth_token_acquired",
        "remote_list_performed",
        "remote_metadata_read_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "file_signature_validated",
        "malware_scan_completed",
        "document_mutated",
        "evidence_admitted",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "checkpoint_advanced",
        "background_sync_started",
    )
    return [
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()) for name in true_fields),
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()) for name in false_fields),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("refresh_execution_verified", "refresh"),
        ("durable_family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("current_document_verified", "current"),
        ("staged_content_proof_verified", "proof"),
        ("human_authorization_recorded", "human"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("oauth_token_acquired", "oauth"),
        ("remote_list_performed", "list"),
        ("remote_metadata_read_performed", "metadata"),
        ("remote_content_read_performed", "content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("file_signature_validated", "signature"),
        ("malware_scan_completed", "malware"),
        ("document_mutated", "document"),
        ("evidence_admitted", "evidence"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_sync_started", "background"),
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_execution_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("handoff_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("expected_prior_document_id", sa.Uuid(), nullable=False),
        sa.Column("expected_prior_version_number", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("refresh_authorization_hash", sa.String(64), nullable=False),
        sa.Column("refresh_completion_hash", sa.String(64), nullable=False),
        sa.Column("decision_completion_hash", sa.String(64), nullable=False),
        sa.Column("handoff_completion_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("observed_projection_hash", sa.String(64), nullable=False),
        sa.Column("observed_version_token_hash", sa.String(64), nullable=True),
        sa.Column("prior_document_file_hash", sa.String(64), nullable=False),
        sa.Column("refreshed_content_sha256", sa.String(64), nullable=False),
        sa.Column("refreshed_content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("refreshed_content_media_type_class", sa.String(128), nullable=True),
        sa.Column("refreshed_content_version_token_hash", sa.String(64), nullable=True),
        sa.Column("refreshed_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False),
        sa.Column("storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="authorized"),
        sa.Column("authorized_by_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_reason", sa.Text(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refresh_execution_id"], ["external_doc_source_observation_refresh_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refresh_authorization_id"], ["external_doc_source_observation_refresh_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_id"], ["external_doc_source_observation_review_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handoff_id"], ["external_doc_source_observation_review_handoffs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["expected_prior_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("refresh_execution_id", name="uq_ext_doc_obs_refresh_adm_auth_exec"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_refresh_adm_auth_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_adm_auth_provider"),
        sa.CheckConstraint("status = 'authorized'", name="ck_ext_doc_obs_refresh_adm_auth_status"),
        sa.CheckConstraint("expected_prior_version_number >= 1", name="ck_ext_doc_obs_refresh_adm_auth_version"),
        sa.CheckConstraint("refreshed_content_byte_count >= 0", name="ck_ext_doc_obs_refresh_adm_auth_size"),
        *_safety_constraints("ext_doc_obs_refresh_adm_auth"),
    )
    op.create_index("ix_ext_doc_obs_refresh_adm_auth_org_claim", AUTH, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_obs_refresh_adm_auth_binding", AUTH, ["binding_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="authorized"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="authorized"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], [f"{AUTH}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("authorization_id", "sequence_number", name="uq_ext_doc_obs_refresh_adm_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_refresh_adm_rcpt_seq"),
        sa.CheckConstraint("event_type = 'authorized'", name="ck_ext_doc_obs_refresh_adm_rcpt_event"),
        sa.CheckConstraint("status_after = 'authorized'", name="ck_ext_doc_obs_refresh_adm_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_obs_refresh_adm_rcpt_prior"),
        *_safety_constraints("ext_doc_obs_refresh_adm_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_obs_refresh_adm_auth_binding", table_name=AUTH)
    op.drop_index("ix_ext_doc_obs_refresh_adm_auth_org_claim", table_name=AUTH)
    op.drop_table(AUTH)
