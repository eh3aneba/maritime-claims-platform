"""add disposal execution manifest preflight

Revision ID: 0111_disposal_execution_manifest
Revises: 0110_disposal_authorization_queue
"""

from alembic import op
import sqlalchemy as sa

revision = "0111_disposal_execution_manifest"
down_revision = "0110_disposal_authorization_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disposal_execution_manifests",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_number", sa.Integer(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inventory", sa.JSON(), nullable=False),
        sa.Column("inventory_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("active_hold_ids", sa.JSON(), nullable=False),
        sa.Column("pending_proposal_ids", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_revalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="ready", nullable=False),
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
            "status IN ('ready', 'blocked', 'invalidated', 'expired')",
            name="ck_disposal_execution_manifest_status",
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('blocked', 'invalidated', 'expired') AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_disposal_execution_manifest_lifecycle",
        ),
        sa.CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_execution_manifest_document_count",
        ),
        sa.CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_execution_manifest_total_bytes",
        ),
        sa.CheckConstraint(
            "manifest_expires_at <= authorization_expires_at",
            name="ck_disposal_execution_manifest_expiry_bound",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
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
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["terminal_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "disposal_authorization_id",
            name="uq_disposal_execution_manifest_authorization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "manifest_hash",
            name="uq_disposal_execution_manifest_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "disposal_authorization_id",
        "retention_policy_id",
        "created_by_id",
        "terminal_by_id",
    ):
        op.create_index(
            op.f(f"ix_disposal_execution_manifests_{column}"),
            "disposal_execution_manifests",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_disposal_execution_manifests_org_claim_status",
        "disposal_execution_manifests",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_disposal_execution_manifests_org_expiry",
        "disposal_execution_manifests",
        ["organization_id", "manifest_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disposal_execution_manifests_org_expiry",
        table_name="disposal_execution_manifests",
    )
    op.drop_index(
        "ix_disposal_execution_manifests_org_claim_status",
        table_name="disposal_execution_manifests",
    )
    for column in (
        "terminal_by_id",
        "created_by_id",
        "retention_policy_id",
        "disposal_authorization_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_disposal_execution_manifests_{column}"),
            table_name="disposal_execution_manifests",
        )
    op.drop_table("disposal_execution_manifests")
