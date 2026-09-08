"""add tenant retention policy and claim legal-hold foundation

Revision ID: 0107_tenant_retention_legal_hold
Revises: 0106_scim_user_lifecycle
"""

from alembic import op
import sqlalchemy as sa

revision = "0107_tenant_retention_legal_hold"
down_revision = "0106_scim_user_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_retention_policies",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("policy_number", sa.Integer(), nullable=False),
        sa.Column("closed_claim_retention_days", sa.Integer(), nullable=False),
        sa.Column("evidence_retention_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "disposal_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_policy_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
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
            "closed_claim_retention_days >= 30 AND closed_claim_retention_days <= 36500",
            name="ck_retention_policy_claim_days",
        ),
        sa.CheckConstraint(
            "evidence_retention_days >= 30 AND evidence_retention_days <= 36500",
            name="ck_retention_policy_evidence_days",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "policy_number",
            name="uq_tenant_retention_policies_org_number",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "policy_hash",
            name="uq_tenant_retention_policies_org_hash",
        ),
    )
    op.create_index(
        op.f("ix_tenant_retention_policies_organization_id"),
        "tenant_retention_policies",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tenant_retention_policies_created_by_id"),
        "tenant_retention_policies",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_retention_policies_org_number",
        "tenant_retention_policies",
        ["organization_id", "policy_number"],
        unique=False,
    )

    op.create_table(
        "claim_legal_holds",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("placed_by_id", sa.Uuid(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_id", sa.Uuid(), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["placed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["released_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_legal_holds_organization_id"),
        "claim_legal_holds",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_legal_holds_claim_id"),
        "claim_legal_holds",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_legal_holds_placed_by_id"),
        "claim_legal_holds",
        ["placed_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_legal_holds_released_by_id"),
        "claim_legal_holds",
        ["released_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_claim_legal_holds_org_claim",
        "claim_legal_holds",
        ["organization_id", "claim_id"],
        unique=False,
    )
    op.create_index(
        "ix_claim_legal_holds_org_claim_release",
        "claim_legal_holds",
        ["organization_id", "claim_id", "released_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_claim_legal_holds_org_claim_release",
        table_name="claim_legal_holds",
    )
    op.drop_index("ix_claim_legal_holds_org_claim", table_name="claim_legal_holds")
    op.drop_index(
        op.f("ix_claim_legal_holds_released_by_id"),
        table_name="claim_legal_holds",
    )
    op.drop_index(
        op.f("ix_claim_legal_holds_placed_by_id"),
        table_name="claim_legal_holds",
    )
    op.drop_index(op.f("ix_claim_legal_holds_claim_id"), table_name="claim_legal_holds")
    op.drop_index(
        op.f("ix_claim_legal_holds_organization_id"),
        table_name="claim_legal_holds",
    )
    op.drop_table("claim_legal_holds")

    op.drop_index(
        "ix_tenant_retention_policies_org_number",
        table_name="tenant_retention_policies",
    )
    op.drop_index(
        op.f("ix_tenant_retention_policies_created_by_id"),
        table_name="tenant_retention_policies",
    )
    op.drop_index(
        op.f("ix_tenant_retention_policies_organization_id"),
        table_name="tenant_retention_policies",
    )
    op.drop_table("tenant_retention_policies")
