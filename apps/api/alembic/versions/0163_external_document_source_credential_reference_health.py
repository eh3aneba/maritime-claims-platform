"""Add external credential-reference health qualification.

Revision ID: 0163_external_document_source_credential_reference_health
Revises: 0162_external_document_source_credential_reference
"""

from alembic import op
import sqlalchemy as sa

revision = "0163_external_document_source_credential_reference_health"
down_revision = "0162_external_document_source_credential_reference"
branch_labels = None
depends_on = None

QUALIFICATION = "external_document_source_credential_reference_health_checks"
RECEIPT = "external_document_source_credential_reference_health_receipts"


def _safety_columns(*, resolution_default: bool):
    return [
        sa.Column("credential_reference_stored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "credential_reference_resolution_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true() if resolution_default else sa.false(),
        ),
        sa.Column("credential_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    ]


def _non_resolution_constraints(prefix: str):
    fields = (
        ("credential_stored", "credential"),
        ("oauth_token_exchanged", "oauth"),
        ("provider_network_performed", "provider_network"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("subscription_created", "subscription"),
        ("sync_executed", "sync"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("claim_mutated", "claim"),
    )
    return [
        sa.CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference_only"),
        *(sa.CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in fields),
    ]


def upgrade() -> None:
    op.create_table(
        QUALIFICATION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("credential_reference_binding_id", sa.Uuid(), nullable=False),
        sa.Column("provider_kind", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("binding_scope_hash", sa.String(64), nullable=False),
        sa.Column("binding_request_hash", sa.String(64), nullable=False),
        sa.Column("binding_approval_hash", sa.String(64), nullable=False),
        sa.Column("locator_hash", sa.String(64), nullable=False),
        sa.Column("reference_backend", sa.String(32), nullable=False),
        sa.Column("resolver_kind", sa.String(128), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        *_safety_columns(resolution_default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["external_document_source_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["credential_reference_binding_id"],
            ["external_document_source_credential_reference_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_reference_binding_id", name="uq_ext_doc_cred_health_binding"),
        sa.UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_cred_health_request"),
        sa.CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_cred_health_provider"),
        sa.CheckConstraint(
            "reference_backend IN ('aws_secrets_manager','azure_key_vault','gcp_secret_manager','hashicorp_vault')",
            name="ck_ext_doc_cred_health_backend",
        ),
        sa.CheckConstraint("result_status IN ('resolvable','unresolvable')", name="ck_ext_doc_cred_health_result"),
        sa.CheckConstraint(
            "(result_status = 'resolvable' AND failure_code IS NULL) OR "
            "(result_status = 'unresolvable' AND failure_code IS NOT NULL)",
            name="ck_ext_doc_cred_health_failure",
        ),
        sa.CheckConstraint("checked_at >= requested_at", name="ck_ext_doc_cred_health_time"),
        sa.CheckConstraint("credential_reference_resolution_performed = true", name="ck_ext_doc_cred_health_resolution"),
        *_non_resolution_constraints("ext_doc_cred_health"),
    )
    op.create_index("ix_ext_doc_cred_health_org_profile", QUALIFICATION, ["organization_id", "profile_id"])
    op.create_index("ix_ext_doc_cred_health_org_result", QUALIFICATION, ["organization_id", "result_status"])
    for name, column in (
        ("ix_ext_doc_cred_health_org", "organization_id"),
        ("ix_ext_doc_cred_health_profile", "profile_id"),
        ("ix_ext_doc_cred_health_binding", "credential_reference_binding_id"),
        ("ix_ext_doc_cred_health_requester", "requested_by_id"),
    ):
        op.create_index(name, QUALIFICATION, [column])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
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
        *_safety_columns(resolution_default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualification_id"], [QUALIFICATION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qualification_id", "sequence_number", name="uq_ext_doc_cred_health_receipt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_cred_health_receipt_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_ext_doc_cred_health_receipt_seq"),
        sa.CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_cred_health_receipt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND credential_reference_resolution_performed = false) OR "
            "(event_type = 'completed' AND status_after IN ('resolvable','unresolvable') AND credential_reference_resolution_performed = true)",
            name="ck_ext_doc_cred_health_receipt_mapping",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_cred_health_receipt_chain",
        ),
        *_non_resolution_constraints("ext_doc_cred_health_receipt"),
    )
    op.create_index("ix_ext_doc_cred_health_receipt_qual_seq", RECEIPT, ["qualification_id", "sequence_number"])
    for name, column in (
        ("ix_ext_doc_cred_health_receipt_org", "organization_id"),
        ("ix_ext_doc_cred_health_receipt_qual", "qualification_id"),
        ("ix_ext_doc_cred_health_receipt_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(QUALIFICATION)
