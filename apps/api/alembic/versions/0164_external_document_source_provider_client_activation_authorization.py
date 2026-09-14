"""Add governed provider-client activation authorization.

Revision ID: 0164_external_document_source_provider_client_activation_authorization
Revises: 0163_external_document_source_credential_reference_health
"""

from alembic import op
import sqlalchemy as sa

revision = "0164_external_document_source_provider_client_activation_authorization"
down_revision = "0163_external_document_source_credential_reference_health"
branch_labels = None
depends_on = None

AUTH = "external_document_source_provider_client_activation_auths"
RECEIPT = "external_doc_source_provider_client_activation_receipts"


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("credential_reference_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_authorization_code_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oauth_token_exchanged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("refresh_token_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("client_secret_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("private_key_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.Column("provider_client_activation_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_reference_resolution_performed", "resolution"),
        ("credential_stored", "credential"),
        ("oauth_authorization_code_stored", "oauth_code"),
        ("oauth_token_exchanged", "oauth"),
        ("access_token_stored", "access_token"),
        ("refresh_token_stored", "refresh_token"),
        ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"),
        ("provider_network_performed", "provider_network"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("subscription_created", "subscription"),
        ("checkpoint_created", "checkpoint"),
        ("sync_executed", "sync"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("binding_scope_hash", sa.String(64), nullable=False),
        sa.Column("binding_request_hash", sa.String(64), nullable=False),
        sa.Column("binding_approval_hash", sa.String(64), nullable=False),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("resolver_kind", sa.String(128), nullable=False),
        sa.Column("health_scope_hash", sa.String(64), nullable=False),
        sa.Column("health_request_hash", sa.String(64), nullable=False),
        sa.Column("health_result_hash", sa.String(64), nullable=False),
        sa.Column("health_result_status", sa.String(24), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("execution_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_second_approval"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("authorization_hash", sa.String(64), nullable=True),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("terminal_hash", sa.String(64), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["health_qualification_id"], ["external_document_source_credential_reference_health_checks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_document_source_credential_reference_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("health_qualification_id", name="uq_ext_doc_pc_act_health"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_pc_act_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_pc_act_provider"),
        sa.CheckConstraint("health_result_status = 'resolvable'", name="ck_ext_doc_pc_act_resolvable"),
        sa.CheckConstraint("status IN ('pending_second_approval','authorized','rejected','expired')", name="ck_ext_doc_pc_act_status"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_ext_doc_pc_act_four_eyes"),
        sa.CheckConstraint("execution_limit = 1", name="ck_ext_doc_pc_act_limit"),
        sa.CheckConstraint(
            "(status = 'authorized' AND provider_client_activation_authorized = true) OR "
            "(status <> 'authorized' AND provider_client_activation_authorized = false)",
            name="ck_ext_doc_pc_act_auth_mapping",
        ),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND authorization_hash IS NULL AND authorization_expires_at IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'authorized' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND authorization_hash IS NOT NULL AND authorization_expires_at IS NOT NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND authorization_hash IS NULL AND authorization_expires_at IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'expired' AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_pc_act_lifecycle",
        ),
        *_safety_constraints("ext_doc_pc_act"),
    )
    op.create_index("ix_ext_doc_pc_act_org_profile", AUTH, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_pc_act_org_status", AUTH, ["organization_id", "status"])
    for name, column in (
        ("ix_ext_doc_pc_act_org", "organization_id"),
        ("ix_ext_doc_pc_act_profile", "profile_id"),
        ("ix_ext_doc_pc_act_health", "health_qualification_id"),
        ("ix_ext_doc_pc_act_binding", "credential_reference_binding_id"),
        ("ix_ext_doc_pc_act_requester", "requested_by_id"),
        ("ix_ext_doc_pc_act_approver", "approved_by_id"),
        ("ix_ext_doc_pc_act_terminal", "terminal_by_id"),
    ):
        op.create_index(name, AUTH, [column])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(["authorization_id"], [AUTH + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "sequence_number", name="uq_ext_doc_pc_act_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_pc_act_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_pc_act_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','authorized','rejected','expired')", name="ck_ext_doc_pc_act_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval' AND provider_client_activation_authorized = false) OR "
            "(event_type = 'authorized' AND status_after = 'authorized' AND provider_client_activation_authorized = true) OR "
            "(event_type = 'rejected' AND status_after = 'rejected' AND provider_client_activation_authorized = false) OR "
            "(event_type = 'expired' AND status_after = 'expired' AND provider_client_activation_authorized = false)",
            name="ck_ext_doc_pc_act_rcpt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_pc_act_rcpt_chain"),
        *_safety_constraints("ext_doc_pc_act_rcpt"),
    )
    op.create_index("ix_ext_doc_pc_act_rcpt_seq", RECEIPT, ["authorization_id", "sequence_number"])
    for name, column in (
        ("ix_ext_doc_pc_act_rcpt_org", "organization_id"),
        ("ix_ext_doc_pc_act_rcpt_auth", "authorization_id"),
        ("ix_ext_doc_pc_act_rcpt_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(AUTH)
