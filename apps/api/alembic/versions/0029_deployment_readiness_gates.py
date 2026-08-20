"""deployment readiness gates

Revision ID: 0029_deployment_readiness
Revises: 0028_external_portal
"""
import sqlalchemy as sa
from alembic import op

revision = "0029_deployment_readiness"
down_revision = "0028_external_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_readiness_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("attested_by_id", sa.Uuid(), nullable=True), sa.Column("environment", sa.String(30), nullable=False),
        sa.Column("review_key", sa.String(120), nullable=False), sa.Column("controls", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), server_default="draft", nullable=False), sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("attestation_note", sa.Text(), nullable=True), sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attested_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "environment", "review_key", name="uq_deployment_readiness_review_key"),
    )
    op.create_index("ix_deployment_readiness_reviews_organization_id", "deployment_readiness_reviews", ["organization_id"])
    op.create_index("ix_deployment_readiness_org_environment", "deployment_readiness_reviews", ["organization_id", "environment", "status"])


def downgrade() -> None:
    op.drop_index("ix_deployment_readiness_org_environment", table_name="deployment_readiness_reviews")
    op.drop_index("ix_deployment_readiness_reviews_organization_id", table_name="deployment_readiness_reviews")
    op.drop_table("deployment_readiness_reviews")
