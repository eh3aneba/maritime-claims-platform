"""four-eyes external portal publication

Revision ID: 0031_portal_publication
Revises: 0030_operational_monitoring
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_portal_publication"
down_revision = "0030_operational_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_portal_publication_proposals",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True), sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("published_item_id", sa.Uuid(), nullable=True), sa.Column("item_type", sa.String(30), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True), sa.Column("status", sa.String(30), server_default="under_review", nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True), sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invitation_id"], ["external_portal_invitations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_item_id"], ["external_portal_published_items.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invitation_id", "item_type", "source_id", name="uq_external_portal_publication_source"),
    )
    op.create_index("ix_external_portal_publication_proposals_organization_id", "external_portal_publication_proposals", ["organization_id"])
    op.create_index("ix_external_portal_publication_proposals_invitation_id", "external_portal_publication_proposals", ["invitation_id"])
    op.create_index("ix_external_portal_publication_org_status", "external_portal_publication_proposals", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_external_portal_publication_org_status", table_name="external_portal_publication_proposals")
    op.drop_index("ix_external_portal_publication_proposals_invitation_id", table_name="external_portal_publication_proposals")
    op.drop_index("ix_external_portal_publication_proposals_organization_id", table_name="external_portal_publication_proposals")
    op.drop_table("external_portal_publication_proposals")
