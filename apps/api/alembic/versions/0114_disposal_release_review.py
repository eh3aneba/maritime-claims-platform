"""add final disposal release review

Revision ID: 0114_disposal_release_review
Revises: 0113_disposal_quarantine_staging
"""

from alembic import op
import sqlalchemy as sa

revision = "0114_disposal_release_review"
down_revision = "0113_disposal_quarantine_staging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disposal_release_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("disposal_quarantine_stage_id", sa.Uuid(), nullable=False),
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
        sa.Column("overlay_hash", sa.String(length=64), nullable=False),
        sa.Column("stage_hash", sa.String(length=64), nullable=False),
        sa.Column("retention_policy_number", sa.Integer(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("release_snapshot", sa.JSON(), nullable=False),
        sa.Column("release_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("review_hash", sa.String(length=64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("quarantine_staged_by_id", sa.Uuid(), nullable=False),
        sa.Column("quarantine_staged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quarantine_stage_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minimum_release_eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_revalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending_final_approval",
            nullable=False,
        ),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("approval_hash", sa.String(length=64), nullable=True),
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
            "status IN ('pending_final_approval', 'approved', 'rejected', 'invalidated', 'expired', 'cancelled')",
            name="ck_disposal_release_review_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending_final_approval' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'approved' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('rejected', 'invalidated', 'expired', 'cancelled') "
            "AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL "
            "AND approval_hash IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL "
            "AND terminal_reason IS NOT NULL)",
            name="ck_disposal_release_review_lifecycle",
        ),
        sa.CheckConstraint(
            "approved_by_id IS NULL OR approved_by_id <> requested_by_id",
            name="ck_disposal_release_review_distinct_requester_approver",
        ),
        sa.CheckConstraint(
            "approved_by_id IS NULL OR approved_by_id <> quarantine_staged_by_id",
            name="ck_disposal_release_review_distinct_stage_creator_approver",
        ),
        sa.CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_release_review_document_count",
        ),
        sa.CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_release_review_total_bytes",
        ),
        sa.CheckConstraint(
            "minimum_release_eligible_at >= quarantine_staged_at",
            name="ck_disposal_release_review_minimum_dwell",
        ),
        sa.CheckConstraint(
            "review_expires_at <= quarantine_stage_expires_at",
            name="ck_disposal_release_review_expiry_bound",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["disposal_quarantine_stage_id"],
            ["disposal_quarantine_stages.id"],
            ondelete="RESTRICT",
        ),
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
        sa.ForeignKeyConstraint(["quarantine_staged_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "disposal_quarantine_stage_id",
            name="uq_disposal_release_review_stage",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "review_hash",
            name="uq_disposal_release_review_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "disposal_quarantine_stage_id",
        "disposal_dry_run_ceremony_id",
        "disposal_execution_manifest_id",
        "disposal_authorization_id",
        "retention_policy_id",
        "quarantine_staged_by_id",
        "requested_by_id",
        "approved_by_id",
        "terminal_by_id",
    ):
        op.create_index(
            op.f(f"ix_disposal_release_reviews_{column}"),
            "disposal_release_reviews",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_disposal_release_reviews_org_claim_status",
        "disposal_release_reviews",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_disposal_release_reviews_org_expiry",
        "disposal_release_reviews",
        ["organization_id", "review_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disposal_release_reviews_org_expiry",
        table_name="disposal_release_reviews",
    )
    op.drop_index(
        "ix_disposal_release_reviews_org_claim_status",
        table_name="disposal_release_reviews",
    )
    for column in (
        "terminal_by_id",
        "approved_by_id",
        "requested_by_id",
        "quarantine_staged_by_id",
        "retention_policy_id",
        "disposal_authorization_id",
        "disposal_execution_manifest_id",
        "disposal_dry_run_ceremony_id",
        "disposal_quarantine_stage_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_disposal_release_reviews_{column}"),
            table_name="disposal_release_reviews",
        )
    op.drop_table("disposal_release_reviews")
