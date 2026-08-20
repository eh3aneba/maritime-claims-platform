"""pilot governance and exit controls

Revision ID: 0032_pilot_governance
Revises: 0031_portal_publication
"""
import sqlalchemy as sa
from alembic import op

revision = "0032_pilot_governance"
down_revision = "0031_portal_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pilot_governance_profiles",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True), sa.Column("pilot_purpose", sa.Text(), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=False), sa.Column("data_owner", sa.String(180), nullable=False),
        sa.Column("retention_statement", sa.Text(), nullable=False), sa.Column("residency_statement", sa.Text(), nullable=False),
        sa.Column("exit_contact", sa.String(320), nullable=False), sa.Column("status", sa.String(30), server_default="draft", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_pilot_governance_profile_org"),
    )
    op.create_index("ix_pilot_governance_profiles_organization_id", "pilot_governance_profiles", ["organization_id"])
    op.create_table(
        "pilot_exit_manifests",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("governance_profile_id", sa.Uuid(), nullable=False), sa.Column("authorized_by_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("confirm_manifest_only", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("manifest_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="authorized", nullable=False), sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["governance_profile_id"], ["pilot_governance_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "idempotency_key", name="uq_pilot_exit_manifest_key"),
    )
    op.create_index("ix_pilot_exit_manifests_organization_id", "pilot_exit_manifests", ["organization_id"])
    op.create_index("ix_pilot_exit_manifests_claim_id", "pilot_exit_manifests", ["claim_id"])
    op.create_index("ix_pilot_exit_manifest_org_claim", "pilot_exit_manifests", ["organization_id", "claim_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_pilot_exit_manifest_org_claim", table_name="pilot_exit_manifests")
    op.drop_index("ix_pilot_exit_manifests_claim_id", table_name="pilot_exit_manifests")
    op.drop_index("ix_pilot_exit_manifests_organization_id", table_name="pilot_exit_manifests"); op.drop_table("pilot_exit_manifests")
    op.drop_index("ix_pilot_governance_profiles_organization_id", table_name="pilot_governance_profiles"); op.drop_table("pilot_governance_profiles")
