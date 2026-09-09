"""add governed disposal authorization queue

Revision ID: 0110_disposal_authorization_queue
Revises: 0109_preservation_signal_intake
"""

from alembic import op
import sqlalchemy as sa

revision = "0110_disposal_authorization_queue"
down_revision = "0109_preservation_signal_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disposal_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_number", sa.Integer(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_retention_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_retention_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligibility_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligibility_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("active_hold_ids", sa.JSON(), nullable=False),
        sa.Column("pending_proposal_ids", sa.JSON(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending_second_approval",
            nullable=False,
        ),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by_id", sa.Uuid(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
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
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_disposal_authorization_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NULL) OR "
            "(status = 'approved' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NOT NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NOT NULL AND rejected_at IS NOT NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NOT NULL) OR "
            "(status IN ('expired', 'invalidated') AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NOT NULL "
            "AND invalidated_at IS NOT NULL AND decision_reason IS NOT NULL)",
            name="ck_disposal_authorization_lifecycle",
        ),
        sa.CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_disposal_authorization_four_eyes",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["retention_policy_id"], ["tenant_retention_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invalidated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_disposal_authorizations_organization_id"),
        "disposal_authorizations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_disposal_authorizations_claim_id"),
        "disposal_authorizations",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_disposal_authorizations_retention_policy_id"),
        "disposal_authorizations",
        ["retention_policy_id"],
        unique=False,
    )
    for column in ("requested_by_id", "approved_by_id", "rejected_by_id", "invalidated_by_id"):
        op.create_index(
            op.f(f"ix_disposal_authorizations_{column}"),
            "disposal_authorizations",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_disposal_authorizations_org_claim_status",
        "disposal_authorizations",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_disposal_authorizations_org_status_expiry",
        "disposal_authorizations",
        ["organization_id", "status", "authorization_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disposal_authorizations_org_status_expiry",
        table_name="disposal_authorizations",
    )
    op.drop_index(
        "ix_disposal_authorizations_org_claim_status",
        table_name="disposal_authorizations",
    )
    for column in ("invalidated_by_id", "rejected_by_id", "approved_by_id", "requested_by_id"):
        op.drop_index(
            op.f(f"ix_disposal_authorizations_{column}"),
            table_name="disposal_authorizations",
        )
    op.drop_index(
        op.f("ix_disposal_authorizations_retention_policy_id"),
        table_name="disposal_authorizations",
    )
    op.drop_index(
        op.f("ix_disposal_authorizations_claim_id"),
        table_name="disposal_authorizations",
    )
    op.drop_index(
        op.f("ix_disposal_authorizations_organization_id"),
        table_name="disposal_authorizations",
    )
    op.drop_table("disposal_authorizations")
