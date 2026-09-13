"""Add Phase 17.4-A physical-disposal admission authorization.

Revision ID: 0155_physical_disposal_admission_authorization
Revises: 0154_durable_authoritative_storage_health_qualification
"""

from alembic import op
import sqlalchemy as sa

revision = "0155_physical_disposal_admission_authorization"
down_revision = "0154_durable_authoritative_storage_health_qualification"
branch_labels = None
depends_on = None

TABLE = "physical_disposal_admission_authorizations"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_release_review_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_quarantine_stage_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_execution_manifest_id", sa.Uuid(), nullable=False),
        sa.Column("release_review_hash", sa.String(64), nullable=False),
        sa.Column("release_approval_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("inventory_hash", sa.String(64), nullable=False),
        sa.Column("document_bindings", sa.JSON(), nullable=False),
        sa.Column("document_bindings_hash", sa.String(64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_second_approval"),
        sa.Column("physical_disposal_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_execution_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("approval_hash", sa.String(64), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["disposal_release_review_id"], ["disposal_release_reviews.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["disposal_quarantine_stage_id"], ["disposal_quarantine_stages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["disposal_execution_manifest_id"], ["disposal_execution_manifests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("disposal_release_review_id", name="uq_physical_disposal_admission_release_review"),
        sa.UniqueConstraint("organization_id", "authorization_hash", name="uq_physical_disposal_admission_org_hash"),
        sa.CheckConstraint(
            "status IN ('pending_second_approval','authorized','rejected','expired','invalidated','consumed')",
            name="ck_physical_disposal_admission_status",
        ),
        sa.CheckConstraint("max_execution_count = 1", name="ck_physical_disposal_admission_single_use"),
        sa.CheckConstraint("execution_count IN (0, 1)", name="ck_physical_disposal_admission_execution_count"),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND physical_disposal_authorized = false "
            "AND execution_count = 0 AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'authorized' AND physical_disposal_authorized = true "
            "AND execution_count = 0 AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'consumed' AND physical_disposal_authorized = true "
            "AND execution_count = 1 AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL) OR "
            "(status IN ('rejected','expired','invalidated') AND physical_disposal_authorized = false "
            "AND execution_count = 0 AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_physical_disposal_admission_lifecycle",
        ),
        sa.CheckConstraint("approved_by_id IS NULL OR approved_by_id <> requested_by_id", name="ck_physical_disposal_admission_four_eyes"),
        sa.CheckConstraint("document_count > 0", name="ck_physical_disposal_admission_document_count"),
        sa.CheckConstraint("total_file_size_bytes >= 0", name="ck_physical_disposal_admission_total_bytes"),
        sa.CheckConstraint("authorization_expires_at > requested_at", name="ck_physical_disposal_admission_expiry"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_physical_disposal_admission_no_destructive_action"),
        sa.CheckConstraint("storage_write_performed = false", name="ck_physical_disposal_admission_no_storage_write"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_physical_disposal_admission_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_physical_disposal_admission_no_local_delete"),
    )
    op.create_index("ix_physical_disposal_admission_org_claim_status", TABLE, ["organization_id", "claim_id", "status"])
    op.create_index("ix_physical_disposal_admission_org_expiry", TABLE, ["organization_id", "authorization_expires_at"])
    for column in (
        "organization_id",
        "claim_id",
        "disposal_release_review_id",
        "disposal_quarantine_stage_id",
        "disposal_execution_manifest_id",
        "requested_by_id",
        "approved_by_id",
        "terminal_by_id",
    ):
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])


def downgrade() -> None:
    op.drop_table(TABLE)
