"""Add explicit external Evidence downstream-processing releases.

Revision ID: 0183_external_doc_source_processing_release
Revises: 0182_external_doc_source_evidence_family_binding
"""

from alembic import op
import sqlalchemy as sa

revision = "0183_external_doc_source_processing_release"
down_revision = "0182_external_doc_source_evidence_family_binding"
branch_labels = None
depends_on = None

RELEASE = "external_doc_source_processing_releases"
RECEIPT = "external_doc_source_processing_release_receipts"


def _safety_columns():
    return [
        sa.Column("family_binding_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_document_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("local_text_processing_authorized", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ai_processing_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_io_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_io_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    return [
        sa.CheckConstraint("family_binding_verified = true", name=f"ck_{prefix}_family"),
        sa.CheckConstraint("current_document_verified = true", name=f"ck_{prefix}_current"),
        sa.CheckConstraint("local_text_processing_authorized = true", name=f"ck_{prefix}_local"),
        sa.CheckConstraint("ai_processing_authorized = false", name=f"ck_{prefix}_no_ai"),
        sa.CheckConstraint("provider_io_performed = false", name=f"ck_{prefix}_no_provider_io"),
        sa.CheckConstraint("storage_io_performed = false", name=f"ck_{prefix}_no_storage_io"),
        sa.CheckConstraint("document_mutated = false", name=f"ck_{prefix}_no_document_mutation"),
        sa.CheckConstraint("processing_enqueued = false", name=f"ck_{prefix}_no_enqueue"),
        sa.CheckConstraint("claim_mutated = false", name=f"ck_{prefix}_no_claim_mutation"),
    ]


def upgrade() -> None:
    op.create_table(
        RELEASE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_number", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("released_by_id", sa.Uuid(), nullable=False),
        sa.Column("release_reason", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_hash", sa.String(64), nullable=False),
        sa.Column("revocation_request_key", sa.String(128), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["external_doc_source_evidence_family_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["released_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id",
            "document_id",
            "document_version_number",
            name="uq_ext_doc_proc_release_binding_version",
        ),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_proc_release_request"),
        sa.UniqueConstraint(
            "organization_id",
            "profile_id",
            "revocation_request_key",
            name="uq_ext_doc_proc_release_revoke_request",
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_ext_doc_proc_release_status"),
        sa.CheckConstraint("document_version_number >= 1", name="ck_ext_doc_proc_release_version"),
        sa.CheckConstraint(
            "(status = 'active' AND revocation_request_key IS NULL AND revoked_by_id IS NULL "
            "AND revocation_reason IS NULL AND revoked_at IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'revoked' AND revocation_request_key IS NOT NULL AND revoked_by_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL AND revoked_at IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_proc_release_revocation_state",
        ),
        *_safety_constraints("ext_doc_proc_release"),
    )
    op.create_index("ix_ext_doc_proc_release_org_claim", RELEASE, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_proc_release_document", RELEASE, ["organization_id", "document_id"])
    op.create_index("ix_ext_doc_proc_release_family", RELEASE, ["organization_id", "document_family_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["release_id"], [RELEASE + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "sequence_number", name="uq_ext_doc_proc_release_rcpt_seq"),
        sa.CheckConstraint("sequence_number IN (1,2)", name="ck_ext_doc_proc_release_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('granted','revoked')", name="ck_ext_doc_proc_release_rcpt_event"),
        sa.CheckConstraint("status_after IN ('active','revoked')", name="ck_ext_doc_proc_release_rcpt_status"),
        sa.CheckConstraint(
            "(sequence_number = 1 AND event_type = 'granted' AND status_after = 'active' "
            "AND prior_receipt_hash IS NULL) OR "
            "(sequence_number = 2 AND event_type = 'revoked' AND status_after = 'revoked' "
            "AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_proc_release_rcpt_lifecycle",
        ),
        *_safety_constraints("ext_doc_proc_release_rcpt"),
    )
    op.create_index("ix_ext_doc_proc_release_rcpt_release", RECEIPT, ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_ext_doc_proc_release_rcpt_release", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_proc_release_family", table_name=RELEASE)
    op.drop_index("ix_ext_doc_proc_release_document", table_name=RELEASE)
    op.drop_index("ix_ext_doc_proc_release_org_claim", table_name=RELEASE)
    op.drop_table(RELEASE)
