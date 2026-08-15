"""claim-scoped external collaboration portal

Revision ID: 0028_external_portal
Revises: 0027_email_provider_adapters
"""
import sqlalchemy as sa
from alembic import op

revision = "0028_external_portal"
down_revision = "0027_email_provider_adapters"
branch_labels = None
depends_on = None


def _base_columns():
    return [sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "external_portal_invitations",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True), sa.Column("participant_name", sa.String(180), nullable=False),
        sa.Column("participant_email", sa.String(320), nullable=False), sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("permission_manifest", sa.JSON(), nullable=False), sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for name, cols in [("ix_external_portal_invitations_organization_id", ["organization_id"]),
                       ("ix_external_portal_invitations_claim_id", ["claim_id"]),
                       ("ix_external_portal_invitations_expires_at", ["expires_at"]),
                       ("ix_external_portal_invite_org_claim_status", ["organization_id", "claim_id", "status"])]:
        op.create_index(name, "external_portal_invitations", cols)
    op.create_table(
        "external_portal_sessions",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invitation_id"], ["external_portal_invitations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("session_hash"),
    )
    for name, cols in [("ix_external_portal_sessions_organization_id", ["organization_id"]),
                       ("ix_external_portal_sessions_invitation_id", ["invitation_id"]),
                       ("ix_external_portal_sessions_expires_at", ["expires_at"])]:
        op.create_index(name, "external_portal_sessions", cols)
    op.create_table(
        "external_portal_published_items",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("published_by_id", sa.Uuid(), nullable=True), sa.Column("item_type", sa.String(30), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True), *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invitation_id"], ["external_portal_invitations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invitation_id", "item_type", "source_id", name="uq_external_portal_published_source"),
    )
    for name, cols in [("ix_external_portal_published_items_organization_id", ["organization_id"]),
                       ("ix_external_portal_published_items_invitation_id", ["invitation_id"]),
                       ("ix_external_portal_published_invite", ["invitation_id", "created_at"])]:
        op.create_index(name, "external_portal_published_items", cols)
    op.create_table(
        "external_portal_submissions",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False), sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("correspondence_id", sa.Uuid(), nullable=True), sa.Column("subject", sa.String(240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False), sa.Column("attachment_manifests", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_review", nullable=False), sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invitation_id"], ["external_portal_invitations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["correspondence_id"], ["claim_correspondence.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in [("ix_external_portal_submissions_organization_id", ["organization_id"]),
                       ("ix_external_portal_submissions_claim_id", ["claim_id"]),
                       ("ix_external_portal_submissions_invitation_id", ["invitation_id"]),
                       ("ix_external_portal_submission_org_claim_status", ["organization_id", "claim_id", "status"])]:
        op.create_index(name, "external_portal_submissions", cols)


def downgrade() -> None:
    for table, names in [
        ("external_portal_submissions", ["ix_external_portal_submission_org_claim_status", "ix_external_portal_submissions_invitation_id", "ix_external_portal_submissions_claim_id", "ix_external_portal_submissions_organization_id"]),
        ("external_portal_published_items", ["ix_external_portal_published_invite", "ix_external_portal_published_items_invitation_id", "ix_external_portal_published_items_organization_id"]),
        ("external_portal_sessions", ["ix_external_portal_sessions_expires_at", "ix_external_portal_sessions_invitation_id", "ix_external_portal_sessions_organization_id"]),
        ("external_portal_invitations", ["ix_external_portal_invite_org_claim_status", "ix_external_portal_invitations_expires_at", "ix_external_portal_invitations_claim_id", "ix_external_portal_invitations_organization_id"]),
    ]:
        for name in names: op.drop_index(name, table_name=table)
        op.drop_table(table)
