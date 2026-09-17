"""Add human-controlled external evidence admission authorization.

Revision ID: 0180_external_doc_source_evidence_admission_authorization
Revises: 0179_external_doc_source_generation_3_change_detection
"""

from alembic import op
import sqlalchemy as sa

revision = "0180_external_doc_source_evidence_admission_authorization"
down_revision = "0179_external_doc_source_generation_3_change_detection"
branch_labels = None
depends_on = None

AUTH = "external_doc_source_evidence_admission_auths"
RECEIPT = "external_doc_source_evidence_admission_auth_receipts"


def _safety_columns():
    true_fields = (
        "upstream_checkpoint_generation_3_advance_completed",
        "upstream_generation_3_change_detection_completed",
        "latest_generation_3_observation_confirmed",
        "remote_version_current_at_authorization",
        "human_authorization_recorded",
    )
    false_fields = (
        "provider_client_constructed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "document_created",
        "evidence_admitted",
        "content_parsed",
        "content_extracted",
        "claim_mutated",
        "admission_execution_performed",
        "background_sync_started",
    )
    return [
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()) for name in true_fields),
        *(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()) for name in false_fields),
    ]


def _safety_constraints(prefix: str):
    true_fields = (
        ("upstream_checkpoint_generation_3_advance_completed", "gen3"),
        ("upstream_generation_3_change_detection_completed", "change"),
        ("latest_generation_3_observation_confirmed", "latest"),
        ("remote_version_current_at_authorization", "current"),
        ("human_authorization_recorded", "human"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("document_created", "document"),
        ("evidence_admitted", "evidence"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
        ("claim_mutated", "claim"),
        ("admission_execution_performed", "execution"),
        ("background_sync_started", "background"),
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
        sa.Column("generation_3_change_detection_execution_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_generation_3_execution_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("authorized_projection_hash", sa.String(64), nullable=False),
        sa.Column("authorized_display_name_hash", sa.String(64), nullable=False),
        sa.Column("authorized_version_token_hash", sa.String(64), nullable=True),
        sa.Column("authorized_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("authorized_mime_type_class", sa.String(128), nullable=True),
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
        sa.ForeignKeyConstraint(["generation_3_change_detection_execution_id"], ["external_doc_source_gen3_change_detect_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checkpoint_generation_3_execution_id"], ["external_doc_source_checkpoint_gen3_execs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_eaa_request"),
        sa.UniqueConstraint("organization_id", "claim_id", "generation_3_change_detection_execution_id", name="uq_ext_doc_eaa_claim_observation"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_eaa_provider"),
        sa.CheckConstraint("status = 'authorized'", name="ck_ext_doc_eaa_status"),
        sa.CheckConstraint("authorized_byte_size IS NULL OR authorized_byte_size >= 0", name="ck_ext_doc_eaa_size"),
        *_safety_constraints("ext_doc_eaa"),
    )
    op.create_index("ix_ext_doc_eaa_org_claim", AUTH, ["organization_id", "claim_id"])
    op.create_index("ix_ext_doc_eaa_org_profile", AUTH, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_eaa_observation", AUTH, ["generation_3_change_detection_execution_id"])

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
        sa.UniqueConstraint("authorization_id", "sequence_number", name="uq_ext_doc_eaa_receipt_sequence"),
        sa.CheckConstraint("sequence_number = 1", name="ck_ext_doc_eaa_receipt_sequence"),
        sa.CheckConstraint("event_type = 'authorized'", name="ck_ext_doc_eaa_receipt_event"),
        sa.CheckConstraint("status_after = 'authorized'", name="ck_ext_doc_eaa_receipt_status"),
        sa.CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_eaa_receipt_prior"),
        *_safety_constraints("ext_doc_eaa_receipt"),
    )
    op.create_index("ix_ext_doc_eaa_receipt_auth", RECEIPT, ["authorization_id"])


def downgrade() -> None:
    op.drop_index("ix_ext_doc_eaa_receipt_auth", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_ext_doc_eaa_observation", table_name=AUTH)
    op.drop_index("ix_ext_doc_eaa_org_profile", table_name=AUTH)
    op.drop_index("ix_ext_doc_eaa_org_claim", table_name=AUTH)
    op.drop_table(AUTH)
