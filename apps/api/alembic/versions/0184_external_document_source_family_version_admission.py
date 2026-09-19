"""Add later-version admission into an existing external Evidence family.

Revision ID: 0184_external_doc_family_version_admission
Revises: 0183_external_doc_source_processing_release
"""

from alembic import op
import sqlalchemy as sa

revision = "0184_external_doc_family_version_admission"
down_revision = "0183_external_doc_source_processing_release"
branch_labels = None
depends_on = None

EXEC = "external_doc_source_family_version_admission_execs"
RECEIPT = "external_doc_source_family_version_admission_receipts"


def _safety_columns():
    return [
        sa.Column("upstream_authorization_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable_family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stable_source_identity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("authorization_single_use_consumed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("latest_generation_3_observation_confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fresh_exact_item_metadata_read_performed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fresh_remote_version_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("staged_content_integrity_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("malware_scan_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("canonical_document_write_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("new_document_created", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("prior_document_superseded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exactly_one_current_version_established", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("later_version_admitted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_content_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("staged_storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("staged_storage_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_parsed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_extracted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_advanced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("background_sync_started", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("upstream_authorization_verified", "auth"),
        ("durable_family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("authorization_single_use_consumed", "single_use"),
        ("latest_generation_3_observation_confirmed", "latest"),
        ("fresh_exact_item_metadata_read_performed", "metadata"),
        ("fresh_remote_version_current", "current"),
        ("staged_content_integrity_verified", "staged"),
        ("malware_scan_completed", "malware"),
        ("canonical_document_write_completed", "canonical"),
        ("new_document_created", "new_doc"),
        ("prior_document_superseded", "superseded"),
        ("exactly_one_current_version_established", "one_current"),
        ("later_version_admitted", "admitted"),
    )
    false_fields = (
        ("remote_list_performed", "list"),
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
        EXEC,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("generation_3_change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_generation_3_execution_id", sa.Uuid(), nullable=False),
        sa.Column("successor_versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("prior_document_id", sa.Uuid(), nullable=False),
        sa.Column("prior_version_number", sa.Integer(), nullable=False),
        sa.Column("new_document_id", sa.Uuid(), nullable=False),
        sa.Column("new_version_number", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorized_projection_hash", sa.String(64), nullable=False),
        sa.Column("observation_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("candidate_completion_hash", sa.String(64), nullable=False),
        sa.Column("prior_projection_hash", sa.String(64), nullable=False),
        sa.Column("prior_provider_version_hash", sa.String(64), nullable=True),
        sa.Column("prior_document_file_hash", sa.String(64), nullable=False),
        sa.Column("fresh_projection_hash", sa.String(64), nullable=False),
        sa.Column("fresh_display_name_hash", sa.String(64), nullable=False),
        sa.Column("fresh_version_token_hash", sa.String(64), nullable=True),
        sa.Column("fresh_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("fresh_mime_type_class", sa.String(128), nullable=True),
        sa.Column("staged_content_sha256", sa.String(64), nullable=False),
        sa.Column("staged_content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("staged_storage_object_key_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["external_doc_source_evidence_admission_auths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["generation_3_change_detection_execution_id"],
            ["external_doc_source_gen3_change_detect_execs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_generation_3_execution_id"],
            ["external_doc_source_checkpoint_gen3_execs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["successor_versioned_restaging_execution_id"],
            ["external_doc_source_successor_versioned_restage_execs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["prior_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["new_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_ext_doc_fva_authorization"),
        sa.UniqueConstraint("new_document_id", name="uq_ext_doc_fva_new_document"),
        sa.UniqueConstraint("binding_id", "prior_document_id", name="uq_ext_doc_fva_prior"),
        sa.UniqueConstraint("binding_id", "new_version_number", name="uq_ext_doc_fva_version"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_fva_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_fva_provider"),
        sa.CheckConstraint("status = 'admitted'", name="ck_ext_doc_fva_status"),
        sa.CheckConstraint("prior_version_number >= 1", name="ck_ext_doc_fva_prior_version"),
        sa.CheckConstraint("new_version_number = prior_version_number + 1", name="ck_ext_doc_fva_next_version"),
        sa.CheckConstraint("fresh_byte_size >= 0", name="ck_ext_doc_fva_fresh_size"),
        sa.CheckConstraint("staged_content_byte_count >= 0", name="ck_ext_doc_fva_staged_size"),
        sa.CheckConstraint("new_document_file_size_bytes >= 0", name="ck_ext_doc_fva_doc_size"),
        *_safety_constraints("ext_doc_fva"),
    )
    op.create_index("ix_ext_doc_fva_org_claim", EXEC, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_fva_org_profile", EXEC, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_fva_binding", EXEC, ["binding_id"])
    op.create_index("ix_ext_doc_fva_prior", EXEC, ["prior_document_id"])
    op.create_index("ix_ext_doc_fva_new", EXEC, ["new_document_id"])

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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], [EXEC + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_fva_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_fva_rcpt_seq"),
        sa.CheckConstraint("event_type = 'admitted'", name="ck_ext_doc_fva_rcpt_event"),
        sa.CheckConstraint("status_after = 'admitted'", name="ck_ext_doc_fva_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_fva_rcpt_prior"),
        *_safety_constraints("ext_doc_fva_rcpt"),
    )
    op.create_index("ix_ext_doc_fva_rcpt_execution", RECEIPT, ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_ext_doc_fva_rcpt_execution", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_fva_new", table_name=EXEC)
    op.drop_index("ix_ext_doc_fva_prior", table_name=EXEC)
    op.drop_index("ix_ext_doc_fva_binding", table_name=EXEC)
    op.drop_index("ix_ext_doc_fva_org_profile", table_name=EXEC)
    op.drop_index("ix_ext_doc_fva_org_claim", table_name=EXEC)
    op.drop_table(EXEC)
