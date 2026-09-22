"""Add canonical observation refresh admissions.

Revision ID: 0193_external_doc_obs_refresh_adm_exec
Revises: 0192_external_doc_obs_refresh_adm_auth
"""

from alembic import op
import sqlalchemy as sa

revision = "0193_external_doc_obs_refresh_adm_exec"
down_revision = "0192_external_doc_obs_refresh_adm_auth"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_observation_refresh_admission_execs"
RECEIPT = "external_doc_source_observation_refresh_admission_receipts"


def _safety_columns():
    true_fields = (
        "authorization_verified",
        "refresh_execution_verified",
        "durable_family_binding_verified",
        "stable_source_identity_verified",
        "authorization_single_use_consumed",
        "current_document_verified",
        "staged_storage_read_performed",
        "staged_content_integrity_verified",
        "file_signature_validated",
        "malware_scan_completed",
        "canonical_document_write_completed",
        "new_document_created",
        "prior_document_superseded",
        "exactly_one_current_version_established",
        "refreshed_version_admitted",
    )
    false_fields = (
        "provider_client_constructed",
        "oauth_token_acquired",
        "remote_list_performed",
        "remote_metadata_read_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "staged_storage_write_performed",
        "staged_storage_delete_performed",
        "content_parsed",
        "content_extracted",
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
        ("authorization_verified", "auth"),
        ("refresh_execution_verified", "refresh"),
        ("durable_family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("authorization_single_use_consumed", "single_use"),
        ("current_document_verified", "current"),
        ("staged_storage_read_performed", "staged_read"),
        ("staged_content_integrity_verified", "staged"),
        ("file_signature_validated", "signature"),
        ("malware_scan_completed", "malware"),
        ("canonical_document_write_completed", "canonical"),
        ("new_document_created", "new_doc"),
        ("prior_document_superseded", "superseded"),
        ("exactly_one_current_version_established", "one_current"),
        ("refreshed_version_admitted", "admitted"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("oauth_token_acquired", "oauth"),
        ("remote_list_performed", "list"),
        ("remote_metadata_read_performed", "metadata"),
        ("remote_content_read_performed", "remote_content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("staged_storage_write_performed", "staged_write"),
        ("staged_storage_delete_performed", "staged_delete"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
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
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_execution_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("prior_document_id", sa.Uuid(), nullable=False),
        sa.Column("prior_version_number", sa.Integer(), nullable=False),
        sa.Column("new_document_id", sa.Uuid(), nullable=False),
        sa.Column("new_version_number", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("refresh_completion_hash", sa.String(64), nullable=False),
        sa.Column("binding_completion_hash", sa.String(64), nullable=False),
        sa.Column("prior_document_file_hash", sa.String(64), nullable=False),
        sa.Column("refreshed_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("refreshed_content_sha256", sa.String(64), nullable=False),
        sa.Column("refreshed_content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("refreshed_content_media_type_class", sa.String(128), nullable=True),
        sa.Column("refreshed_content_version_token_hash", sa.String(64), nullable=True),
        sa.Column("staged_storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("staged_storage_purpose", sa.String(128), nullable=False),
        sa.Column("staged_storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("validated_file_suffix", sa.String(16), nullable=False),
        sa.Column("malware_scan_verdict", sa.String(16), nullable=False),
        sa.Column("security_verification_hash", sa.String(64), nullable=False),
        sa.Column("new_document_file_hash", sa.String(64), nullable=False),
        sa.Column("new_document_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("new_document_filename_hash", sa.String(64), nullable=False),
        sa.Column("canonical_storage_key_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="admitted"),
        sa.Column("executed_by_id", sa.Uuid(), nullable=False),
        sa.Column("execution_reason", sa.Text(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["external_doc_source_observation_refresh_admission_auths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refresh_execution_id"], ["external_doc_source_observation_refresh_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["new_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("authorization_id", name="uq_ext_doc_obs_refresh_adm_exec_auth"),
        sa.UniqueConstraint("new_document_id", name="uq_ext_doc_obs_refresh_adm_exec_new_doc"),
        sa.UniqueConstraint("binding_id", "prior_document_id", name="uq_ext_doc_obs_refresh_adm_exec_prior"),
        sa.UniqueConstraint("binding_id", "new_version_number", name="uq_ext_doc_obs_refresh_adm_exec_version"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_refresh_adm_exec_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_adm_exec_provider"),
        sa.CheckConstraint("status = 'admitted'", name="ck_ext_doc_obs_refresh_adm_exec_status"),
        sa.CheckConstraint("prior_version_number >= 1", name="ck_ext_doc_obs_refresh_adm_exec_prior_ver"),
        sa.CheckConstraint("new_version_number = prior_version_number + 1", name="ck_ext_doc_obs_refresh_adm_exec_next_ver"),
        sa.CheckConstraint("refreshed_content_byte_count >= 0", name="ck_ext_doc_obs_refresh_adm_exec_size"),
        sa.CheckConstraint("new_document_file_size_bytes >= 0", name="ck_ext_doc_obs_refresh_adm_exec_doc_size"),
        sa.CheckConstraint("malware_scan_verdict = 'clean'", name="ck_ext_doc_obs_refresh_adm_exec_malware_verdict"),
        *_safety_constraints("ext_doc_obs_refresh_adm_exec"),
    )
    op.create_index("ix_ext_doc_obs_refresh_adm_exec_org_claim", EXECUTION, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_obs_refresh_adm_exec_binding", EXECUTION, ["binding_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="admitted"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="admitted"),
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
        sa.ForeignKeyConstraint(["execution_id"], [f"{EXECUTION}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_obs_refresh_adm_exec_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_seq"),
        sa.CheckConstraint("event_type = 'admitted'", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_event"),
        sa.CheckConstraint("status_after = 'admitted'", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_prior"),
        *_safety_constraints("ext_doc_obs_refresh_adm_rcpt"),
    )


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_obs_refresh_adm_exec_binding", table_name=EXECUTION)
    op.drop_index("ix_ext_doc_obs_refresh_adm_exec_org_claim", table_name=EXECUTION)
    op.drop_table(EXECUTION)
