"""Add governed external evidence admission execution.

Revision ID: 0181_external_doc_source_evidence_admission_execution
Revises: 0180_external_doc_source_evidence_admission_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0181_external_doc_source_evidence_admission_execution"
down_revision = "0180_external_doc_source_evidence_admission_authorization"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_evidence_admission_execs"
RECEIPT = "external_doc_source_evidence_admission_exec_receipts"


def _safety_columns():
    true_fields = (
        "upstream_authorization_verified",
        "authorization_single_use_consumed",
        "latest_generation_3_observation_confirmed",
        "fresh_exact_item_metadata_read_performed",
        "fresh_remote_version_current",
        "staged_content_integrity_verified",
        "malware_scan_completed",
        "canonical_document_write_completed",
        "document_created",
        "evidence_admitted",
        "admission_execution_performed",
    )
    false_fields = (
        "remote_list_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "staged_storage_write_performed",
        "staged_storage_delete_performed",
        "content_parsed",
        "content_extracted",
        "processing_enqueued",
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
        ("upstream_authorization_verified", "auth"),
        ("authorization_single_use_consumed", "single_use"),
        ("latest_generation_3_observation_confirmed", "latest"),
        ("fresh_exact_item_metadata_read_performed", "metadata"),
        ("fresh_remote_version_current", "current"),
        ("staged_content_integrity_verified", "staged_integrity"),
        ("malware_scan_completed", "malware"),
        ("canonical_document_write_completed", "canonical_write"),
        ("document_created", "document"),
        ("evidence_admitted", "evidence"),
        ("admission_execution_performed", "execution"),
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
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("generation_3_change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_generation_3_execution_id", sa.Uuid(), nullable=False),
        sa.Column("successor_versioned_restaging_execution_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorized_projection_hash", sa.String(64), nullable=False),
        sa.Column("observation_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("candidate_completion_hash", sa.String(64), nullable=False),
        sa.Column("fresh_projection_hash", sa.String(64), nullable=False),
        sa.Column("fresh_display_name_hash", sa.String(64), nullable=False),
        sa.Column("fresh_version_token_hash", sa.String(64), nullable=True),
        sa.Column("fresh_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("fresh_mime_type_class", sa.String(128), nullable=True),
        sa.Column("staged_content_sha256", sa.String(64), nullable=False),
        sa.Column("staged_content_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("staged_storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("document_file_hash", sa.String(64), nullable=False),
        sa.Column("document_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("document_filename_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["authorization_id"], ["external_doc_source_evidence_admission_auths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation_3_change_detection_execution_id"], ["external_doc_source_gen3_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checkpoint_generation_3_execution_id"], ["external_doc_source_checkpoint_gen3_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["successor_versioned_restaging_execution_id"], ["external_doc_source_successor_versioned_restage_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_ext_doc_eae_authorization"),
        sa.UniqueConstraint("document_id", name="uq_ext_doc_eae_document"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_eae_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_eae_provider"),
        sa.CheckConstraint("status = 'admitted'", name="ck_ext_doc_eae_status"),
        sa.CheckConstraint("fresh_byte_size >= 0", name="ck_ext_doc_eae_fresh_size"),
        sa.CheckConstraint("staged_content_byte_count >= 0", name="ck_ext_doc_eae_staged_size"),
        sa.CheckConstraint("document_file_size_bytes >= 0", name="ck_ext_doc_eae_document_size"),
        *_safety_constraints("ext_doc_eae"),
    )
    op.create_index("ix_ext_doc_eae_org_claim", EXECUTION, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_eae_org_profile", EXECUTION, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_eae_authorization", EXECUTION, ["authorization_id"])
    op.create_index("ix_ext_doc_eae_document", EXECUTION, ["document_id"])

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
        sa.ForeignKeyConstraint(["execution_id"], [EXECUTION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_eae_receipt_sequence"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_eae_receipt_sequence"),
        sa.CheckConstraint("event_type = 'admitted'", name="ck_ext_doc_eae_receipt_event"),
        sa.CheckConstraint("status_after = 'admitted'", name="ck_ext_doc_eae_receipt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_eae_receipt_prior"),
        *_safety_constraints("ext_doc_eae_receipt"),
    )
    op.create_index("ix_ext_doc_eae_receipt_execution", RECEIPT, ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_ext_doc_eae_receipt_execution", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_eae_document", table_name=EXECUTION)
    op.drop_index("ix_ext_doc_eae_authorization", table_name=EXECUTION)
    op.drop_index("ix_ext_doc_eae_org_profile", table_name=EXECUTION)
    op.drop_index("ix_ext_doc_eae_org_claim", table_name=EXECUTION)
    op.drop_table(EXECUTION)