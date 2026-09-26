"""Add bounded SFTP authentication and subsystem activation.

Revision ID: 0200_external_doc_source_sftp_session_activation
Revises: 0199_external_doc_source_sftp_transport_verification
"""

from alembic import op
import sqlalchemy as sa

revision = "0200_external_doc_source_sftp_session_activation"
down_revision = "0199_external_doc_source_sftp_transport_verification"
branch_labels = None
depends_on = None

ACTIVATION = "external_doc_source_sftp_session_activations"
RECEIPT = "external_doc_source_sftp_session_activation_receipts"


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("secret_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ssh_transport_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verification_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authentication_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authentication_succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sftp_session_opened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sftp_session_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_stat_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_rename_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_stored", "credential"),
        ("remote_list_performed", "list"),
        ("remote_stat_performed", "stat"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_rename_performed", "rename"),
        ("remote_delete_performed", "delete"),
        ("command_executed", "command"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
        sa.CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth_order"),
        sa.CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_session_auth"),
        sa.CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_session_closed"),
        sa.CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host_key"),
    ]


def upgrade() -> None:
    op.create_table(
        ACTIVATION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("transport_verification_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("transport_verification_scope_hash", sa.String(64), nullable=False),
        sa.Column("transport_verification_request_hash", sa.String(64), nullable=False),
        sa.Column("transport_verification_result_hash", sa.String(64), nullable=False),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("authentication_kind", sa.String(32), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("destination_hostname", sa.String(253), nullable=False),
        sa.Column("destination_port", sa.Integer(), nullable=False),
        sa.Column("pinned_host_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("adapter_kind", sa.String(128), nullable=False),
        sa.Column("activation_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("authentication_method", sa.String(32), nullable=True),
        sa.Column("latency_class", sa.String(24), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transport_verification_id"], ["external_doc_source_sftp_transport_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["health_qualification_id"], ["external_doc_source_sftp_cred_health_checks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_reference_binding_id"], ["external_doc_source_sftp_cred_ref_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transport_verification_id", name="uq_ext_doc_sftp_session_activation_verify"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_session_activation_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_session_activation_provider"),
        sa.CheckConstraint("authentication_kind IN ('password','private_key')", name="ck_ext_doc_sftp_session_activation_auth_kind"),
        sa.CheckConstraint("activation_limit = 1", name="ck_ext_doc_sftp_session_activation_limit"),
        sa.CheckConstraint("result_status IN ('activated','failed')", name="ck_ext_doc_sftp_session_activation_result"),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'credential_resolution_failed','credential_unavailable','authentication_failed',"
            "'authentication_timeout','unsupported_authentication_method','host_key_revalidation_failed',"
            "'sftp_subsystem_activation_failed','destination_policy_violation','adapter_boundary_violation',"
            "'invalid_adapter_result','adapter_error'"
            ")",
            name="ck_ext_doc_sftp_session_activation_failure",
        ),
        sa.CheckConstraint("latency_class IS NULL OR latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_session_activation_latency"),
        sa.CheckConstraint(
            "(result_status = 'activated' AND failure_code IS NULL "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true) OR "
            "(result_status = 'failed' AND failure_code IS NOT NULL)",
            name="ck_ext_doc_sftp_session_activation_outcome",
        ),
        sa.CheckConstraint("checked_at >= requested_at", name="ck_ext_doc_sftp_session_activation_time"),
        *_safety_constraints("ext_doc_sftp_session_activation"),
    )
    op.create_index("ix_ext_doc_sftp_session_activation_org_profile", ACTIVATION, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_sftp_session_activation_org_result", ACTIVATION, ["organization_id", "result_status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("activation_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["activation_id"], [ACTIVATION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activation_id", "sequence_number", name="uq_ext_doc_sftp_session_activation_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_session_activation_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_session_activation_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_session_activation_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND authentication_performed = false "
            "AND sftp_session_opened = false) OR "
            "(event_type = 'completed' AND status_after IN ('activated','failed'))",
            name="ck_ext_doc_sftp_session_activation_rcpt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_session_activation_rcpt_chain",
        ),
        *_safety_constraints("ext_doc_sftp_session_activation_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_session_activation_rcpt_seq", RECEIPT, ["activation_id", "sequence_number"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(ACTIVATION)
