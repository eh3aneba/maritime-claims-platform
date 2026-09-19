"""Add durable external Evidence source-item family binding.

Revision ID: 0182_external_doc_source_evidence_family_binding
Revises: 0181_external_doc_source_evidence_admission_execution
"""

from alembic import op
import sqlalchemy as sa

revision = "0182_external_doc_source_evidence_family_binding"
down_revision = "0181_external_doc_source_evidence_admission_execution"
branch_labels = None
depends_on = None

BINDING = "external_doc_source_evidence_family_bindings"
RECEIPT = "external_doc_source_evidence_family_binding_receipts"


def _safety_columns():
    true_fields = (
        "upstream_admission_verified",
        "stable_source_identity_derived",
        "document_family_verified",
        "version_baseline_recorded",
    )
    false_fields = (
        "provider_client_constructed",
        "remote_metadata_read_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "document_created",
        "document_mutated",
        "processing_enqueued",
        "content_extracted",
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
    always_true = (
        ("upstream_admission_verified", "admission"),
        ("stable_source_identity_derived", "identity"),
        ("document_family_verified", "family"),
        ("version_baseline_recorded", "baseline"),
    )
    always_false = (
        ("provider_client_constructed", "client"),
        ("remote_metadata_read_performed", "metadata"),
        ("remote_content_read_performed", "remote_content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("document_created", "document_create"),
        ("document_mutated", "document_mutate"),
        ("processing_enqueued", "processing"),
        ("content_extracted", "extract"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_sync_started", "background"),
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in always_true),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in always_false),
    ]


def upgrade() -> None:
    op.create_table(
        BINDING,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("admission_execution_id", sa.Uuid(), nullable=False),
        sa.Column("initial_document_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("stable_source_item_hash", sa.String(64), nullable=False),
        sa.Column("source_projection_hash", sa.String(64), nullable=False),
        sa.Column("source_observation_completion_hash", sa.String(64), nullable=False),
        sa.Column("admission_completion_hash", sa.String(64), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("admitted_content_sha256", sa.String(64), nullable=False),
        sa.Column("admitted_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("admitted_mime_type_class", sa.String(128), nullable=True),
        sa.Column("admitted_provider_version_hash", sa.String(64), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("bound_by_id", sa.Uuid(), nullable=False),
        sa.Column("binding_reason", sa.Text(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["admission_execution_id"],
            ["external_doc_source_evidence_admission_execs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["initial_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_family_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bound_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admission_execution_id", name="uq_ext_doc_efb_admission"),
        sa.UniqueConstraint("initial_document_id", name="uq_ext_doc_efb_initial_doc"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "profile_id",
            "stable_source_item_hash",
            name="uq_ext_doc_efb_source",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "document_family_id",
            name="uq_ext_doc_efb_family",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "profile_id",
            "request_key",
            name="uq_ext_doc_efb_request",
        ),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_efb_provider"),
        sa.CheckConstraint("status = 'active'", name="ck_ext_doc_efb_status"),
        sa.CheckConstraint("current_version_number = 1", name="ck_ext_doc_efb_version"),
        sa.CheckConstraint("admitted_byte_count >= 0", name="ck_ext_doc_efb_size"),
        *_safety_constraints("ext_doc_efb"),
    )
    op.create_index("ix_ext_doc_efb_org_claim", BINDING, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_efb_org_profile", BINDING, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_efb_source", BINDING, ["stable_source_item_hash"])
    op.create_index("ix_ext_doc_efb_family", BINDING, ["document_family_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="bound"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="active"),
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
        sa.ForeignKeyConstraint(["binding_id"], [BINDING + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "sequence_number", name="uq_ext_doc_efb_rcpt_seq"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_efb_rcpt_seq"),
        sa.CheckConstraint("event_type = 'bound'", name="ck_ext_doc_efb_rcpt_event"),
        sa.CheckConstraint("status_after = 'active'", name="ck_ext_doc_efb_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_efb_rcpt_prior"),
        *_safety_constraints("ext_doc_efb_rcpt"),
    )
    op.create_index("ix_ext_doc_efb_rcpt_binding", RECEIPT, ["binding_id"])


def downgrade() -> None:
    op.drop_index("ix_ext_doc_efb_rcpt_binding", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_efb_family", table_name=BINDING)
    op.drop_index("ix_ext_doc_efb_source", table_name=BINDING)
    op.drop_index("ix_ext_doc_efb_org_profile", table_name=BINDING)
    op.drop_index("ix_ext_doc_efb_org_claim", table_name=BINDING)
    op.drop_table(BINDING)
