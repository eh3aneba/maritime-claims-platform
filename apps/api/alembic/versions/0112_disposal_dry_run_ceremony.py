"""add disposal dry-run ceremony and attestation

Revision ID: 0112_disposal_dry_run_ceremony
Revises: 0111_disposal_execution_manifest
"""

from alembic import op
import sqlalchemy as sa

revision = "0112_disposal_dry_run_ceremony"
down_revision = "0111_disposal_execution_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disposal_dry_run_ceremonies",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_execution_manifest_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("inventory_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("retention_policy_number", sa.Integer(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dry_run_plan", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("ceremony_hash", sa.String(length=64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("opening_reason", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ceremony_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_revalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending_attestation", nullable=False),
        sa.Column("attested_by_id", sa.Uuid(), nullable=True),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attestation_hash", sa.String(length=64), nullable=True),
        sa.Column("attestation_reason", sa.Text(), nullable=True),
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
            "status IN ('pending_attestation', 'attested', 'blocked', 'invalidated', 'expired', 'cancelled')",
            name="ck_disposal_dry_run_ceremony_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending_attestation' AND attested_by_id IS NULL AND attested_at IS NULL "
            "AND attestation_hash IS NULL AND attestation_reason IS NULL "
            "AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'attested' AND attested_by_id IS NOT NULL AND attested_at IS NOT NULL "
            "AND attestation_hash IS NOT NULL AND attestation_reason IS NOT NULL "
            "AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('blocked', 'invalidated', 'expired', 'cancelled') "
            "AND attested_by_id IS NULL AND attested_at IS NULL AND attestation_hash IS NULL "
            "AND attestation_reason IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_disposal_dry_run_ceremony_lifecycle",
        ),
        sa.CheckConstraint(
            "attested_by_id IS NULL OR attested_by_id <> created_by_id",
            name="ck_disposal_dry_run_ceremony_distinct_attester",
        ),
        sa.CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_dry_run_ceremony_document_count",
        ),
        sa.CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_dry_run_ceremony_total_bytes",
        ),
        sa.CheckConstraint(
            "ceremony_expires_at <= manifest_expires_at",
            name="ck_disposal_dry_run_ceremony_expiry_bound",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "disposal_execution_manifest_id",
            name="uq_disposal_dry_run_ceremony_manifest",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "ceremony_hash",
            name="uq_disposal_dry_run_ceremony_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "disposal_execution_manifest_id",
        "disposal_authorization_id",
        "retention_policy_id",
        "created_by_id",
        "attested_by_id",
        "terminal_by_id",
    ):
        op.create_index(
            op.f(f"ix_disposal_dry_run_ceremonies_{column}"),
            "disposal_dry_run_ceremonies",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_disposal_dry_run_ceremonies_org_claim_status",
        "disposal_dry_run_ceremonies",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_disposal_dry_run_ceremonies_org_expiry",
        "disposal_dry_run_ceremonies",
        ["organization_id", "ceremony_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disposal_dry_run_ceremonies_org_expiry",
        table_name="disposal_dry_run_ceremonies",
    )
    op.drop_index(
        "ix_disposal_dry_run_ceremonies_org_claim_status",
        table_name="disposal_dry_run_ceremonies",
    )
    for column in (
        "terminal_by_id",
        "attested_by_id",
        "created_by_id",
        "retention_policy_id",
        "disposal_authorization_id",
        "disposal_execution_manifest_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_disposal_dry_run_ceremonies_{column}"),
            table_name="disposal_dry_run_ceremonies",
        )
    op.drop_table("disposal_dry_run_ceremonies")
