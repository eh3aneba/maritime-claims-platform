"""database foundation

Revision ID: 0001_database_foundation
Revises:
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_database_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

organization_status = sa.Enum("active", "inactive", name="organization_status")
user_role = sa.Enum("admin", "claims_manager", "claims_handler", name="user_role")
claim_type = sa.Enum("hull_machinery", name="claim_type")
claim_subtype = sa.Enum("machinery_damage", name="claim_subtype")
claim_status = sa.Enum(
    "new", "triage", "awaiting_documents", "investigation", "technical_review",
    "financial_review", "coverage_review", "negotiation", "settlement", "recovery",
    "closed", "on_hold", "litigation", "rejected", "withdrawn", name="claim_status"
)
claim_priority = sa.Enum("low", "medium", "high", "critical", name="claim_priority")
document_processing_status = sa.Enum(
    "uploaded", "processing", "processed", "failed", name="document_processing_status"
)
confidentiality_level = sa.Enum(
    "internal", "confidential", "restricted", name="confidentiality_level"
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", organization_status, server_default="active", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organizations_slug_active",
        "organizations",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "users",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "email", name="uq_users_org_email"),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"], unique=False)
    op.create_index("ix_users_org_active", "users", ["organization_id", "is_active"], unique=False)

    op.create_table(
        "vessels",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("imo_number", sa.String(length=7), nullable=True),
        sa.Column("vessel_type", sa.String(length=100), nullable=True),
        sa.Column("flag", sa.String(length=100), nullable=True),
        sa.Column("class_society", sa.String(length=150), nullable=True),
        sa.Column("year_built", sa.Integer(), nullable=True),
        sa.Column("gross_tonnage", sa.Numeric(14, 2), nullable=True),
        sa.Column("deadweight", sa.Numeric(14, 2), nullable=True),
        sa.Column("owner", sa.String(length=200), nullable=True),
        sa.Column("manager", sa.String(length=200), nullable=True),
        sa.Column("technical_manager", sa.String(length=200), nullable=True),
        sa.Column("call_sign", sa.String(length=30), nullable=True),
        sa.Column("mmsi", sa.String(length=20), nullable=True),
        sa.Column("engine_maker", sa.String(length=150), nullable=True),
        sa.Column("engine_model", sa.String(length=150), nullable=True),
        sa.Column("engine_power_kw", sa.Numeric(12, 2), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "imo_number", name="uq_vessels_org_imo"),
    )
    op.create_index("ix_vessels_organization_id", "vessels", ["organization_id"], unique=False)
    op.create_index("ix_vessels_org_name", "vessels", ["organization_id", "name"], unique=False)

    op.create_table(
        "claims",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("vessel_id", sa.Uuid(), nullable=False),
        sa.Column("handler_id", sa.Uuid(), nullable=True),
        sa.Column("claim_reference", sa.String(length=50), nullable=False),
        sa.Column("external_reference", sa.String(length=100), nullable=True),
        sa.Column("claim_type", claim_type, server_default="hull_machinery", nullable=False),
        sa.Column("claim_subtype", claim_subtype, server_default="machinery_damage", nullable=False),
        sa.Column("status", claim_status, server_default="new", nullable=False),
        sa.Column("priority", claim_priority, server_default="medium", nullable=False),
        sa.Column("incident_date", sa.Date(), nullable=False),
        sa.Column("notification_date", sa.Date(), nullable=False),
        sa.Column("incident_description", sa.Text(), nullable=False),
        sa.Column("estimated_loss", sa.Numeric(18, 2), nullable=True),
        sa.Column("current_reserve", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(currency) = 3", name="ck_claims_currency_len"),
        sa.ForeignKeyConstraint(["handler_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vessel_id"], ["vessels.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_reference", name="uq_claims_org_reference"),
    )
    op.create_index("ix_claims_handler_id", "claims", ["handler_id"], unique=False)
    op.create_index("ix_claims_organization_id", "claims", ["organization_id"], unique=False)
    op.create_index("ix_claims_vessel_id", "claims", ["vessel_id"], unique=False)
    op.create_index("ix_claims_org_status", "claims", ["organization_id", "status"], unique=False)
    op.create_index("ix_claims_org_incident_date", "claims", ["organization_id", "incident_date"], unique=False)

    op.create_table(
        "documents",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_document_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=True),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("version_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("processing_status", document_processing_status, server_default="uploaded", nullable=False),
        sa.Column("confidentiality_level", confidentiality_level, server_default="confidential", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "file_hash", name="uq_documents_claim_hash"),
    )
    op.create_index("ix_documents_claim_id", "documents", ["claim_id"], unique=False)
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"], unique=False)
    op.create_index("ix_documents_org_claim", "documents", ["organization_id", "claim_id"], unique=False)
    op.create_index("ix_documents_org_processing", "documents", ["organization_id", "processing_status"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"], unique=False)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.create_index("ix_audit_org_created", "audit_logs", ["organization_id", "created_at"], unique=False)
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_index("ix_audit_org_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_organization_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_documents_org_processing", table_name="documents")
    op.drop_index("ix_documents_org_claim", table_name="documents")
    op.drop_index("ix_documents_organization_id", table_name="documents")
    op.drop_index("ix_documents_claim_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_claims_org_incident_date", table_name="claims")
    op.drop_index("ix_claims_org_status", table_name="claims")
    op.drop_index("ix_claims_vessel_id", table_name="claims")
    op.drop_index("ix_claims_organization_id", table_name="claims")
    op.drop_index("ix_claims_handler_id", table_name="claims")
    op.drop_table("claims")

    op.drop_index("ix_vessels_org_name", table_name="vessels")
    op.drop_index("ix_vessels_organization_id", table_name="vessels")
    op.drop_table("vessels")

    op.drop_index("ix_users_org_active", table_name="users")
    op.drop_index("ix_users_organization_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_organizations_slug_active", table_name="organizations")
    op.drop_table("organizations")

    confidentiality_level.drop(op.get_bind(), checkfirst=True)
    document_processing_status.drop(op.get_bind(), checkfirst=True)
    claim_priority.drop(op.get_bind(), checkfirst=True)
    claim_status.drop(op.get_bind(), checkfirst=True)
    claim_subtype.drop(op.get_bind(), checkfirst=True)
    claim_type.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
    organization_status.drop(op.get_bind(), checkfirst=True)
