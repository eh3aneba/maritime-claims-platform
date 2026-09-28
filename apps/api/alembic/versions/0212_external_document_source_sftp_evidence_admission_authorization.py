"""Add human-controlled initial SFTP Evidence admission authorization.

Revision ID: 0212_sftp_evidence_admission_authorization
Revises: 0211_sftp_generation3_change_detection
"""

from alembic import op
import sqlalchemy as sa

revision = "0212_sftp_evidence_admission_authorization"
down_revision = "0211_sftp_generation3_change_detection"
branch_labels = None
depends_on = None

AUTH = "external_doc_source_sftp_evidence_admission_auths"
RECEIPT = "external_doc_source_sftp_evidence_admission_auth_receipts"


def _safety_columns():
    true_fields = (
        "upstream_generation3_checkpoint_completed",
        "upstream_generation3_observation_completed",
        "latest_generation3_observation_confirmed",
        "remote_version_current_at_authorization",
        "human_authorization_recorded",
    )
    false_fields = (
        "credential_stored",
        "session_stored",
        "provider_network_performed",
        "ssh_transport_performed",
        "authentication_performed",
        "sftp_session_opened",
        "remote_content_transiently_observed",
        "remote_list_performed",
        "remote_stat_performed",
        "remote_read_performed",
        "remote_write_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_reconciliation_performed",
        "durable_content_staged",
        "checkpoint_created",
        "checkpoint_advanced",
        "document_created",
        "evidence_admitted",
        "content_parsed",
        "content_extracted",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "background_sync_started",
    )
    return [
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()) for name in true_fields),
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()) for name in false_fields),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("upstream_generation3_checkpoint_completed", "q"),
        ("upstream_generation3_observation_completed", "r"),
        ("latest_generation3_observation_confirmed", "latest"),
        ("remote_version_current_at_authorization", "current"),
        ("human_authorization_recorded", "human"),
    )
    false_fields = (
        ("credential_stored", "cred"),
        ("session_stored", "sess"),
        ("provider_network_performed", "net"),
        ("ssh_transport_performed", "ssh"),
        ("authentication_performed", "auth"),
        ("sftp_session_opened", "sftp"),
        ("remote_content_transiently_observed", "content"),
        ("remote_list_performed", "list"),
        ("remote_stat_performed", "stat"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("storage_read_performed", "sread"),
        ("storage_write_performed", "swrite"),
        ("storage_reconciliation_performed", "srecon"),
        ("durable_content_staged", "stage"),
        ("checkpoint_created", "cpcreate"),
        ("checkpoint_advanced", "cpadvance"),
        ("document_created", "doc"),
        ("evidence_admitted", "evidence"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extract"),
        ("processing_enqueued", "process"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("background_sync_started", "bg"),
    )
    return [
        *(sa.CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    ]


def upgrade() -> None:
    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("generation3_change_detection_id", sa.Uuid(), nullable=False),
        sa.Column("generation3_checkpoint_advancement_id", sa.Uuid(), nullable=False),
        sa.Column("generation3_restaging_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("authorized_projection_hash", sa.String(64), nullable=False),
        sa.Column("authorized_entry_hash", sa.String(64), nullable=False),
        sa.Column("authorized_relative_path_hash", sa.String(64), nullable=False),
        sa.Column("authorized_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("authorized_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_metadata_id_hash", sa.String(64), nullable=True),
        sa.Column("authorized_content_sha256", sa.String(64), nullable=False),
        sa.Column("authorized_storage_object_key_hash", sa.String(64), nullable=False),
        sa.Column("storage_backend_kind", sa.String(128), nullable=False),
        sa.Column("storage_purpose", sa.String(128), nullable=False),
        sa.Column("checkpoint_state_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_completion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_content_proof_hash", sa.String(64), nullable=False),
        sa.Column("candidate_completion_hash", sa.String(64), nullable=False),
        sa.Column("observation_completion_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="authorized"),
        sa.Column("authorized_by_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_reason", sa.Text(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation3_change_detection_id"], ["external_doc_source_sftp_generation3_change_detections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation3_checkpoint_advancement_id"], ["external_doc_source_sftp_generation3_checkpoint_advancements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation3_restaging_id"], ["external_doc_source_sftp_generation3_restaging.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_sftp_eaa_request"),
        sa.UniqueConstraint("organization_id", "claim_id", "generation3_change_detection_id", name="uq_sftp_eaa_claim_obs"),
        sa.CheckConstraint("provider_kind = 'sftp'", name="ck_sftp_eaa_provider"),
        sa.CheckConstraint("status = 'authorized'", name="ck_sftp_eaa_status"),
        sa.CheckConstraint("authorized_byte_size >= 0", name="ck_sftp_eaa_size"),
        *_safety_constraints("sftp_eaa"),
    )
    op.create_index("ix_sftp_eaa_org_claim", AUTH, ["organization_id", "claim_id"])
    op.create_index("ix_sftp_eaa_org_profile", AUTH, ["organization_id", "profile_id"])
    op.create_index("ix_sftp_eaa_observation", AUTH, ["generation3_change_detection_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(24), nullable=False, server_default="authorized"),
        sa.Column("status_after", sa.String(24), nullable=False, server_default="authorized"),
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
        sa.ForeignKeyConstraint(["authorization_id"], [AUTH + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", "sequence_number", name="uq_sftp_eaa_rcpt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_sftp_eaa_rcpt_hash"),
        sa.CheckConstraint("sequence_number = 1", name="ck_sftp_eaa_rcpt_seq"),
        sa.CheckConstraint("event_type = 'authorized'", name="ck_sftp_eaa_rcpt_event"),
        sa.CheckConstraint("status_after = 'authorized'", name="ck_sftp_eaa_rcpt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_sftp_eaa_rcpt_prior"),
        *_safety_constraints("sftp_eaa_rcpt"),
    )
    op.create_index("ix_sftp_eaa_rcpt_auth", RECEIPT, ["authorization_id"])


def downgrade() -> None:
    op.drop_index("ix_sftp_eaa_rcpt_auth", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_sftp_eaa_observation", table_name=AUTH)
    op.drop_index("ix_sftp_eaa_org_profile", table_name=AUTH)
    op.drop_index("ix_sftp_eaa_org_claim", table_name=AUTH)
    op.drop_table(AUTH)
