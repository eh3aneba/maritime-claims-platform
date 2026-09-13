"""Add bounded external provider bootstrap authorization consumption.

Revision ID: 0161_external_document_source_connection_bootstrap_consumption
Revises: 0160_external_document_source_connection_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0161_external_document_source_connection_bootstrap_consumption"
down_revision = "0160_external_document_source_connection_authorization"
branch_labels = None
depends_on = None

EXECUTION = "external_document_source_connection_bootstrap_executions"
RECEIPT = "external_document_source_connection_bootstrap_execution_receipts"


def _safety_columns():
    return [
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_token_exchanged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authorization_consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _non_execution_constraints(prefix: str):
    names = {
        "credential_stored": "credential",
        "credential_reference_stored": "credential_reference",
        "oauth_token_exchanged": "oauth",
        "provider_network_performed": "provider_network",
        "remote_list_performed": "list",
        "remote_read_performed": "read",
        "remote_write_performed": "write",
        "remote_delete_performed": "delete",
        "subscription_created": "subscription",
        "sync_executed": "sync",
        "evidence_admitted": "evidence",
        "document_created": "document",
        "claim_mutated": "claim",
    }
    return [sa.CheckConstraint(f"{column} = false", name=f"ck_{prefix}_no_{suffix}") for column, suffix in names.items()]


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("discovery_scope_hash", sa.String(64), nullable=False),
        sa.Column("discovery_manifest_hash", sa.String(64), nullable=False),
        sa.Column("discovery_run_hash", sa.String(64), nullable=False),
        sa.Column("authorization_scope_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_terminal_hash", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["external_document_source_discovery_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["external_document_source_connection_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_ext_doc_conn_bootstrap_authorization"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_conn_bootstrap_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_conn_bootstrap_provider"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_conn_bootstrap_status"),
        sa.CheckConstraint(
            "(status = 'requested' AND authorization_terminal_hash IS NULL AND completed_at IS NULL AND completion_hash IS NULL AND authorization_consumed = false) OR "
            "(status = 'completed' AND authorization_terminal_hash IS NOT NULL AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND authorization_consumed = true)",
            name="ck_ext_doc_conn_bootstrap_lifecycle",
        ),
        *_non_execution_constraints("ext_doc_conn_bootstrap"),
    )
    op.create_index("ix_ext_doc_conn_bootstrap_org_profile", EXECUTION, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_conn_bootstrap_org_status", EXECUTION, ["organization_id", "status"])
    for name, column in (
        ("ix_ext_doc_conn_bootstrap_org", "organization_id"),
        ("ix_ext_doc_conn_bootstrap_profile", "profile_id"),
        ("ix_ext_doc_conn_bootstrap_discovery", "discovery_run_id"),
        ("ix_ext_doc_conn_bootstrap_authorization", "authorization_id"),
        ("ix_ext_doc_conn_bootstrap_requested", "requested_by_id"),
    ):
        op.create_index(name, EXECUTION, [column])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["execution_id"], [EXECUTION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_conn_bootstrap_receipt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_conn_bootstrap_receipt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_conn_bootstrap_receipt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_conn_bootstrap_receipt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND authorization_consumed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND authorization_consumed = true)",
            name="ck_ext_doc_conn_bootstrap_receipt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_conn_bootstrap_receipt_chain",
        ),
        *_non_execution_constraints("ext_doc_conn_bootstrap_receipt"),
    )
    op.create_index("ix_ext_doc_conn_bootstrap_receipt_exec_seq", RECEIPT, ["execution_id", "sequence_number"])
    for name, column in (
        ("ix_ext_doc_conn_bootstrap_receipt_org", "organization_id"),
        ("ix_ext_doc_conn_bootstrap_receipt_exec", "execution_id"),
        ("ix_ext_doc_conn_bootstrap_receipt_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
