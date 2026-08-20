"""external AI provider activation and evaluation gate

Revision ID: 0038_ai_activation
Revises: 0037_operational_acceptance
"""
import sqlalchemy as sa
from alembic import op

revision = "0038_ai_activation"
down_revision = "0037_operational_acceptance"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_provider_activation_requests",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(30), server_default="staging", nullable=False),
        sa.Column("provider", sa.String(40), server_default="openai", nullable=False),
        sa.Column("provider_project_label", sa.String(180), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("data_mode", sa.String(40), server_default="synthetic_deidentified", nullable=False),
        sa.Column("allowed_document_types", sa.JSON(), nullable=False),
        sa.Column("restricted_documents_allowed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("credential_storage_mode", sa.String(40), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False),
        sa.Column("tokens_per_minute", sa.Integer(), nullable=False),
        sa.Column("monthly_spend_limit_cents", sa.Integer(), nullable=False),
        sa.Column("spend_alert_thresholds", sa.JSON(), nullable=False),
        sa.Column("retention_mode", sa.String(50), nullable=False),
        sa.Column("data_residency_region", sa.String(160), nullable=False),
        sa.Column("security_owner_label", sa.String(180), nullable=False),
        sa.Column("privacy_owner_label", sa.String(180), nullable=False),
        sa.Column("product_owner_label", sa.String(180), nullable=False),
        sa.Column("incident_owner_label", sa.String(180), nullable=False),
        sa.Column("kill_switch_owner_label", sa.String(180), nullable=False),
        sa.Column("credential_control_reference", sa.String(500), nullable=False),
        sa.Column("spend_limit_reference", sa.String(500), nullable=False),
        sa.Column("data_processing_reference", sa.String(500), nullable=False),
        sa.Column("kill_switch_reference", sa.String(500), nullable=False),
        sa.Column("evaluation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "request_key", name="uq_ai_provider_activation_key"),
        sa.UniqueConstraint("organization_id", "environment", "provider", "attempt_number",
                            name="uq_ai_provider_activation_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_provider_activation_attempt"),
        sa.CheckConstraint("environment = 'staging'", name="ck_ai_provider_activation_staging"),
        sa.CheckConstraint("provider = 'openai'", name="ck_ai_provider_activation_openai"),
        sa.CheckConstraint("restricted_documents_allowed = false",
                           name="ck_ai_provider_activation_no_restricted"),
    )
    op.create_index("ix_ai_provider_activation_requests_organization_id",
                    "ai_provider_activation_requests", ["organization_id"])
    op.create_index("ix_ai_provider_activation_org_status", "ai_provider_activation_requests",
                    ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_provider_activation_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("activation_request_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_request_id"],
                                ["ai_provider_activation_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activation_request_id", "approval_role",
                            name="uq_ai_provider_activation_approval_role"),
        sa.CheckConstraint("approval_role IN ('security', 'privacy', 'product')",
                           name="ck_ai_provider_approval_role"),
        sa.CheckConstraint("action IN ('approve', 'reject')", name="ck_ai_provider_approval_action"),
    )
    op.create_index("ix_ai_provider_activation_approvals_organization_id",
                    "ai_provider_activation_approvals", ["organization_id"])
    op.create_index("ix_ai_provider_activation_approvals_activation_request_id",
                    "ai_provider_activation_approvals", ["activation_request_id"])
    op.create_index("ix_ai_provider_approval_org_request", "ai_provider_activation_approvals",
                    ["organization_id", "activation_request_id"])

    op.create_table(
        "ai_document_eligibility_attestations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("activation_request_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attested_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attestation_number", sa.Integer(), nullable=False),
        sa.Column("data_mode", sa.String(30), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("confidentiality_level", sa.String(30), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="eligible", nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_request_id"],
                                ["ai_provider_activation_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "attestation_number",
                            name="uq_ai_document_eligibility_attempt"),
        sa.CheckConstraint("attestation_number >= 1", name="ck_ai_document_eligibility_attempt"),
        sa.CheckConstraint("data_mode IN ('synthetic', 'deidentified')",
                           name="ck_ai_document_eligibility_data_mode"),
    )
    op.create_index("ix_ai_document_eligibility_attestations_organization_id",
                    "ai_document_eligibility_attestations", ["organization_id"])
    op.create_index("ix_ai_document_eligibility_attestations_activation_request_id",
                    "ai_document_eligibility_attestations", ["activation_request_id"])
    op.create_index("ix_ai_document_eligibility_attestations_claim_id",
                    "ai_document_eligibility_attestations", ["claim_id"])
    op.create_index("ix_ai_document_eligibility_attestations_document_id",
                    "ai_document_eligibility_attestations", ["document_id"])
    op.create_index("ix_ai_document_eligibility_org_status",
                    "ai_document_eligibility_attestations",
                    ["organization_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_document_eligibility_attestations")
    op.drop_table("ai_provider_activation_approvals")
    op.drop_table("ai_provider_activation_requests")
