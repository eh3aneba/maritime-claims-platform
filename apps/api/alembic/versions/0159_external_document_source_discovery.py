"""Add governed read-only external document source discovery.

Revision ID: 0159_external_document_source_discovery
Revises: 0158_external_document_source_profiles
"""

from alembic import op
import sqlalchemy as sa

revision = "0159_external_document_source_discovery"
down_revision = "0158_external_document_source_profiles"
branch_labels = None
depends_on = None

RUN = "external_document_source_discovery_runs"
ITEM = "external_document_source_discovery_items"
RECEIPT = "external_document_source_discovery_receipts"


def _safety_columns():
    return [
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_token_exchanged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_connection_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _non_list_constraints(prefix: str):
    names = {
        "credential_stored": "credential",
        "oauth_token_exchanged": "oauth",
        "remote_read_performed": "read",
        "remote_write_performed": "write",
        "remote_delete_performed": "delete",
        "subscription_created": "subscription",
        "sync_executed": "sync",
        "evidence_admitted": "evidence",
        "document_created": "document",
        "claim_mutated": "claim",
        "live_connection_authorized": "live_authority",
    }
    return [sa.CheckConstraint(f"{column} = false", name=f"ck_{prefix}_no_{suffix}") for column, suffix in names.items()]


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        RUN,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("max_results", sa.Integer(), nullable=False),
        sa.Column("adapter_kind", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("run_hash", sa.String(64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_discovery_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_discovery_provider"),
        sa.CheckConstraint("status = 'completed'", name="ck_ext_doc_discovery_status"),
        sa.CheckConstraint("max_results > 0 AND max_results <= 500", name="ck_ext_doc_discovery_limit"),
        sa.CheckConstraint("result_count >= 0 AND result_count <= max_results", name="ck_ext_doc_discovery_count"),
        sa.CheckConstraint("remote_list_performed = true", name="ck_ext_doc_discovery_list_performed"),
        *_non_list_constraints("ext_doc_discovery"),
    )
    op.create_index("ix_ext_doc_discovery_org_profile", RUN, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_discovery_org", RUN, ["organization_id"])
    op.create_index("ix_ext_doc_discovery_profile", RUN, ["profile_id"])
    op.create_index("ix_ext_doc_discovery_requester", RUN, ["requested_by_id"])

    op.create_table(
        ITEM,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("provider_item_id", sa.String(512), nullable=False),
        sa.Column("parent_item_id", sa.String(512), nullable=True),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("item_kind", sa.String(16), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_etag", sa.String(512), nullable=True),
        sa.Column("item_hash", sa.String(64), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], [RUN + ".id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_ext_doc_discovery_item_ordinal"),
        sa.UniqueConstraint("run_id", "provider_item_id", name="uq_ext_doc_discovery_item_provider"),
        sa.CheckConstraint("ordinal > 0", name="ck_ext_doc_discovery_item_ordinal"),
        sa.CheckConstraint("item_kind IN ('file','folder')", name="ck_ext_doc_discovery_item_kind"),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_ext_doc_discovery_item_size"),
    )
    op.create_index("ix_ext_doc_discovery_item_run_ordinal", ITEM, ["run_id", "ordinal"])
    op.create_index("ix_ext_doc_discovery_item_org", ITEM, ["organization_id"])
    op.create_index("ix_ext_doc_discovery_item_run", ITEM, ["run_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=True),
        sa.Column("run_hash", sa.String(64), nullable=True),
        sa.Column("prior_receipt_hash", sa.String(64), nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], [RUN + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_ext_doc_discovery_receipt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_discovery_receipt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_discovery_receipt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_discovery_receipt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND remote_list_performed = false AND manifest_hash IS NULL AND run_hash IS NULL) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND remote_list_performed = true AND manifest_hash IS NOT NULL AND run_hash IS NOT NULL)",
            name="ck_ext_doc_discovery_receipt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_discovery_receipt_chain"),
        *_non_list_constraints("ext_doc_discovery_receipt"),
    )
    op.create_index("ix_ext_doc_discovery_receipt_run_seq", RECEIPT, ["run_id", "sequence_number"])
    op.create_index("ix_ext_doc_discovery_receipt_org", RECEIPT, ["organization_id"])
    op.create_index("ix_ext_doc_discovery_receipt_run", RECEIPT, ["run_id"])
    op.create_index("ix_ext_doc_discovery_receipt_actor", RECEIPT, ["actor_id"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(ITEM)
    op.drop_table(RUN)
