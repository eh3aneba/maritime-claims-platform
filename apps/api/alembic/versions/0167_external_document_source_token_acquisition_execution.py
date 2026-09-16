"""Add bounded OAuth/token acquisition execution.

Revision ID: 0167_external_doc_source_token_acquisition_exec
Revises: 0166_external_doc_source_credential_resolution_exec
"""

from alembic import op
import sqlalchemy as sa

revision = "0167_external_doc_source_token_acquisition_exec"
down_revision = "0166_external_doc_source_credential_resolution_exec"
branch_labels = None
depends_on = None

EXECUTION = "external_doc_source_token_acquisition_execs"
RECEIPT = "external_doc_source_token_acquisition_receipts"


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("credential_reference_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("activation_authorization_consumed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("token_acquisition_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_token_exchanged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_endpoint_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_authorization_code_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("refresh_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("client_secret_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("private_key_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_client_constructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_data_api_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_stored", "credential"), ("oauth_authorization_code_stored", "oauth_code"),
        ("access_token_stored", "access_token"), ("refresh_token_stored", "refresh_token"),
        ("id_token_stored", "id_token"), ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"), ("provider_client_constructed", "provider_client"),
        ("provider_data_api_performed", "data_api"), ("remote_list_performed", "list"),
        ("remote_read_performed", "read"), ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"), ("subscription_created", "subscription"),
        ("checkpoint_created", "checkpoint"), ("sync_executed", "sync"),
        ("evidence_admitted", "evidence"), ("document_created", "document"), ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        sa.CheckConstraint("credential_reference_resolution_performed = true", name=f"ck_{prefix}_resolved"),
        sa.CheckConstraint("activation_authorization_consumed = true", name=f"ck_{prefix}_consumed"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("credential_resolution_execution_id", sa.Uuid(), nullable=False),
        sa.Column("activation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("resolution_resolver_kind", sa.String(128), nullable=False),
        sa.Column("credential_resolution_scope_hash", sa.String(64), nullable=False),
        sa.Column("credential_resolution_request_hash", sa.String(64), nullable=False),
        sa.Column("credential_resolution_completion_hash", sa.String(64), nullable=False),
        sa.Column("token_flow_kind", sa.String(32), nullable=False),
        sa.Column("acquirer_kind", sa.String(128), nullable=False),
        sa.Column("endpoint_policy_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("result_status", sa.String(24), nullable=True),
        sa.Column("expiry_class", sa.String(24), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_resolution_execution_id"], ["external_doc_source_credential_resolution_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_execution_id"], ["external_doc_source_provider_client_activation_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["external_document_source_provider_client_activation_auths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["health_qualification_id"], ["external_document_source_credential_reference_health_checks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_document_source_credential_reference_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_resolution_execution_id", name="uq_ext_doc_tok_exec_resolution"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_tok_exec_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_tok_exec_provider"),
        sa.CheckConstraint("token_flow_kind IN ('client_credentials','jwt_bearer')", name="ck_ext_doc_tok_exec_flow"),
        sa.CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_tok_exec_status"),
        sa.CheckConstraint("result_status IS NULL OR result_status = 'acquired'", name="ck_ext_doc_tok_exec_result"),
        sa.CheckConstraint("expiry_class IS NULL OR expiry_class IN ('short','standard','long','unknown')", name="ck_ext_doc_tok_exec_expiry"),
        sa.CheckConstraint(
            "(status = 'requested' AND completed_at IS NULL AND completion_hash IS NULL AND result_status IS NULL AND expiry_class IS NULL AND token_acquisition_performed = false AND oauth_token_exchanged = false AND token_endpoint_network_performed = false) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND result_status = 'acquired' AND expiry_class IS NOT NULL AND token_acquisition_performed = true AND oauth_token_exchanged = true AND token_endpoint_network_performed = true)",
            name="ck_ext_doc_tok_exec_lifecycle",
        ),
        *_safety_constraints("ext_doc_tok_exec"),
    )
    op.create_index("ix_ext_doc_tok_exec_org_profile", EXECUTION, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_tok_exec_org_status", EXECUTION, ["organization_id", "status"])
    for name, column in (
        ("ix_ext_doc_tok_exec_org", "organization_id"), ("ix_ext_doc_tok_exec_profile", "profile_id"),
        ("ix_ext_doc_tok_exec_resolution", "credential_resolution_execution_id"), ("ix_ext_doc_tok_exec_activation", "activation_execution_id"),
        ("ix_ext_doc_tok_exec_auth", "authorization_id"), ("ix_ext_doc_tok_exec_health", "health_qualification_id"),
        ("ix_ext_doc_tok_exec_binding", "credential_reference_binding_id"), ("ix_ext_doc_tok_exec_requester", "requested_by_id"),
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
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_tok_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_tok_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_tok_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_tok_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND token_acquisition_performed = false AND oauth_token_exchanged = false AND token_endpoint_network_performed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND token_acquisition_performed = true AND oauth_token_exchanged = true AND token_endpoint_network_performed = true)",
            name="ck_ext_doc_tok_rcpt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_tok_rcpt_chain"),
        *_safety_constraints("ext_doc_tok_rcpt"),
    )
    op.create_index("ix_ext_doc_tok_rcpt_seq", RECEIPT, ["execution_id", "sequence_number"])
    for name, column in (
        ("ix_ext_doc_tok_rcpt_org", "organization_id"), ("ix_ext_doc_tok_rcpt_exec", "execution_id"), ("ix_ext_doc_tok_rcpt_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(EXECUTION)
