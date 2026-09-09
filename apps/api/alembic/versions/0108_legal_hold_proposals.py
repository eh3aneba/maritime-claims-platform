"""add automated legal-hold proposal controls

Revision ID: 0108_legal_hold_proposals
Revises: 0107_tenant_retention_legal_hold
"""

from alembic import op
import sqlalchemy as sa

revision = "0108_legal_hold_proposals"
down_revision = "0107_tenant_retention_legal_hold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_hold_proposals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("recommended_hold_source", sa.String(length=40), nullable=False),
        sa.Column("source_ref_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("hold_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
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
            "status IN ('pending', 'activated', 'rejected')",
            name="ck_legal_hold_proposal_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND hold_id IS NULL AND decided_at IS NULL AND decided_by_id IS NULL AND decision_reason IS NULL) OR "
            "(status = 'activated' AND hold_id IS NOT NULL AND decided_at IS NOT NULL AND decided_by_id IS NOT NULL AND decision_reason IS NOT NULL) OR "
            "(status = 'rejected' AND hold_id IS NULL AND decided_at IS NOT NULL AND decided_by_id IS NOT NULL AND decision_reason IS NOT NULL)",
            name="ck_legal_hold_proposal_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["hold_id"], ["claim_legal_holds.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "source_kind",
            "source_ref_fingerprint",
            name="uq_legal_hold_proposal_signal_identity",
        ),
    )
    op.create_index(
        op.f("ix_legal_hold_proposals_organization_id"),
        "legal_hold_proposals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_legal_hold_proposals_claim_id"),
        "legal_hold_proposals",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_legal_hold_proposals_hold_id"),
        "legal_hold_proposals",
        ["hold_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_legal_hold_proposals_decided_by_id"),
        "legal_hold_proposals",
        ["decided_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_legal_hold_proposals_org_claim_status",
        "legal_hold_proposals",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_legal_hold_proposals_org_claim_status",
        table_name="legal_hold_proposals",
    )
    op.drop_index(
        op.f("ix_legal_hold_proposals_decided_by_id"),
        table_name="legal_hold_proposals",
    )
    op.drop_index(
        op.f("ix_legal_hold_proposals_hold_id"),
        table_name="legal_hold_proposals",
    )
    op.drop_index(
        op.f("ix_legal_hold_proposals_claim_id"),
        table_name="legal_hold_proposals",
    )
    op.drop_index(
        op.f("ix_legal_hold_proposals_organization_id"),
        table_name="legal_hold_proposals",
    )
    op.drop_table("legal_hold_proposals")
