"""add reversible logical quarantine staging

Revision ID: 0113_disposal_quarantine_staging
Revises: 0112_disposal_dry_run_ceremony
"""

from alembic import op
import sqlalchemy as sa

revision = "0113_disposal_quarantine_staging"
down_revision = "0112_disposal_dry_run_ceremony"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disposal_quarantine_stages",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_dry_run_ceremony_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_execution_manifest_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("inventory_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("ceremony_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("attestation_hash", sa.String(length=64), nullable=False),
        sa.Column("retention_policy_number", sa.Integer(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("ceremony_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overlay_plan", sa.JSON(), nullable=False),
        sa.Column("overlay_hash", sa.String(length=64), nullable=False),
        sa.Column("stage_hash", sa.String(length=64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("staged_by_id", sa.Uuid(), nullable=False),
        sa.Column("staging_reason", sa.Text(), nullable=False),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_revalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="staged", nullable=False),
        sa.Column("restored_by_id", sa.Uuid(), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restoration_reason", sa.Text(), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('staged', 'restored', 'invalidated', 'expired', 'cancelled')",
            name="ck_disposal_quarantine_stage_status",
        ),
        sa.CheckConstraint(
            "(status = 'staged' AND restored_by_id IS NULL AND restored_at IS NULL "
            "AND restoration_reason IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'restored' AND restored_by_id IS NOT NULL AND restored_at IS NOT NULL "
            "AND restoration_reason IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('invalidated', 'expired', 'cancelled') "
            "AND restored_by_id IS NULL AND restored_at IS NULL "
            "AND restoration_reason IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_disposal_quarantine_stage_lifecycle",
        ),
        sa.CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_quarantine_stage_document_count",
        ),
        sa.CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_quarantine_stage_total_bytes",
        ),
        sa.CheckConstraint(
            "stage_expires_at <= ceremony_expires_at",
            name="ck_disposal_quarantine_stage_expiry_bound",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["disposal_dry_run_ceremony_id"],
            ["disposal_dry_run_ceremonies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["disposal_execution_manifest_id"],
            ["disposal_execution_manifests.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["disposal_authorization_id"],
            ["disposal_authorizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_policy_id"],
            ["tenant_retention_policies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["staged_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restored_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "disposal_dry_run_ceremony_id",
            name="uq_disposal_quarantine_stage_ceremony",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "stage_hash",
            name="uq_disposal_quarantine_stage_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "disposal_dry_run_ceremony_id",
        "disposal_execution_manifest_id",
        "disposal_authorization_id",
        "retention_policy_id",
        "staged_by_id",
        "restored_by_id",
        "terminal_by_id",
    ):
        op.create_index(
            op.f(f"ix_disposal_quarantine_stages_{column}"),
            "disposal_quarantine_stages",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_disposal_quarantine_stages_org_claim_status",
        "disposal_quarantine_stages",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_disposal_quarantine_stages_org_expiry",
        "disposal_quarantine_stages",
        ["organization_id", "stage_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disposal_quarantine_stages_org_expiry",
        table_name="disposal_quarantine_stages",
    )
    op.drop_index(
        "ix_disposal_quarantine_stages_org_claim_status",
        table_name="disposal_quarantine_stages",
    )
    for column in (
        "terminal_by_id",
        "restored_by_id",
        "staged_by_id",
        "retention_policy_id",
        "disposal_authorization_id",
        "disposal_execution_manifest_id",
        "disposal_dry_run_ceremony_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_disposal_quarantine_stages_{column}"),
            table_name="disposal_quarantine_stages",
        )
    op.drop_table("disposal_quarantine_stages")
