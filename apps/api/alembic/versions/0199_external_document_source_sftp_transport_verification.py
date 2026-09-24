"""Add bounded SFTP transport and host-key verification.

Revision ID: 0199_external_doc_source_sftp_transport_verification
Revises: 0198_external_doc_source_sftp_handshake_execution
"""

from alembic import op
import sqlalchemy as sa

revision = "0199_external_doc_source_sftp_transport_verification"
down_revision = "0198_external_doc_source_sftp_handshake_execution"
branch_labels = None
depends_on = None

VERIFY = "external_doc_source_sftp_transport_verifications"
RECEIPT = "external_doc_source_sftp_transport_verification_receipts"


def _safety_columns():
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider_network_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ssh_transport_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verification_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host_key_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("secret_resolution_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authentication_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sftp_session_opened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_list_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_read_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_admitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_enqueued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claim_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    false_fields = (
        ("secret_resolution_performed", "resolution"),
        ("credential_stored", "credential"),
        ("authentication_performed", "authentication"),
        ("sftp_session_opened", "session"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        VERIFY,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("handshake_execution_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("handshake_execution_scope_hash", sa.String(64), nullable=False),
        sa.Column("handshake_execution_request_hash", sa.String(64), nullable=False),
        sa.Column("handshake_execution_completion_hash", sa.String(64), nullable=False),
        sa.Column("authorization_terminal_hash", sa.String(64), nullable=False),
        sa.Column("destination_hostname", sa.String(253), nullable=False),
        sa.Column("destination_port", sa.Integer(), nullable=False),
        sa.Column("pinned_host_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("adapter_kind", sa.String(128), nullable=False),
        sa.Column("verification_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("host_key_algorithm", sa.String(64), nullable=True),
        sa.Column("latency_class", sa.String(24), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handshake_execution_id"], ["external_doc_source_sftp_handshake_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("handshake_execution_id", name="uq_ext_doc_sftp_transport_verify_exec"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_transport_verify_request"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_transport_verify_provider"),
        sa.CheckConstraint("verification_limit = 1", name="ck_ext_doc_sftp_transport_verify_limit"),
        sa.CheckConstraint("destination_port BETWEEN 1 AND 65535", name="ck_ext_doc_sftp_transport_verify_port"),
        sa.CheckConstraint("result_status IN ('verified','failed')", name="ck_ext_doc_sftp_transport_verify_result"),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'destination_policy_violation','dns_resolution_failed','connection_timeout',"
            "'connection_refused','network_unavailable','ssh_negotiation_failed',"
            "'host_key_mismatch','unsupported_host_key_algorithm','invalid_adapter_result','adapter_error'"
            ")",
            name="ck_ext_doc_sftp_transport_verify_failure",
        ),
        sa.CheckConstraint(
            "latency_class IS NULL OR latency_class IN ('fast','normal','slow')",
            name="ck_ext_doc_sftp_transport_verify_latency",
        ),
        sa.CheckConstraint("checked_at >= requested_at", name="ck_ext_doc_sftp_transport_verify_time"),
        sa.CheckConstraint(
            "(result_status = 'verified' AND failure_code IS NULL AND host_key_algorithm IS NOT NULL "
            "AND latency_class IS NOT NULL AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true) OR "
            "(result_status = 'failed' AND failure_code IS NOT NULL AND host_key_verified = false)",
            name="ck_ext_doc_sftp_transport_verify_outcome",
        ),
        sa.CheckConstraint(
            "host_key_verified = false OR host_key_verification_performed = true",
            name="ck_ext_doc_sftp_transport_verify_verified",
        ),
        *_safety_constraints("ext_doc_sftp_transport_verify"),
    )
    op.create_index("ix_ext_doc_sftp_transport_verify_org_profile", VERIFY, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_sftp_transport_verify_org_result", VERIFY, ["organization_id", "result_status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["verification_id"], [VERIFY + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("verification_id", "sequence_number", name="uq_ext_doc_sftp_transport_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_transport_rcpt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_transport_rcpt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_transport_rcpt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND provider_network_performed = false AND ssh_transport_performed = false "
            "AND host_key_verification_performed = false AND host_key_verified = false) OR "
            "(event_type = 'completed' AND status_after IN ('verified','failed'))",
            name="ck_ext_doc_sftp_transport_rcpt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_transport_rcpt_chain",
        ),
        *_safety_constraints("ext_doc_sftp_transport_rcpt"),
    )
    op.create_index("ix_ext_doc_sftp_transport_rcpt_seq", RECEIPT, ["verification_id", "sequence_number"])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(VERIFY)
