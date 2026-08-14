"""controlled claim correspondence centre

Revision ID: 0023_correspondence_centre
Revises: 0022_claim_pack_exports
"""

import sqlalchemy as sa

from alembic import op


revision = "0023_correspondence_centre"
down_revision = "0022_claim_pack_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    direction = sa.Enum("outbound", "inbound", "internal", name="correspondence_direction")
    kind = sa.Enum("document_request", "follow_up", "status_update", "reservation_of_rights", "settlement", "general", name="correspondence_kind")
    item_status = sa.Enum("draft", "under_review", "approved", "rejected", "sent_externally", "received_external", "filed_internal", "cancelled", name="correspondence_status")
    sensitivity = sa.Enum("standard", "confidential", "privileged_confidential", "without_prejudice", name="correspondence_sensitivity")
    channel = sa.Enum("email", "letter", "portal", "phone", "meeting", "other", name="correspondence_channel")

    op.create_table(
        "claim_correspondence",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("request_batch_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("sent_by_id", sa.Uuid(), nullable=True),
        sa.Column("direction", direction, nullable=False),
        sa.Column("kind", kind, nullable=False),
        sa.Column("status", item_status, nullable=False),
        sa.Column("sensitivity", sensitivity, nullable=False),
        sa.Column("channel", channel, nullable=True),
        sa.Column("sender_label", sa.String(length=180), nullable=True),
        sa.Column("recipient_label", sa.String(length=180), nullable=True),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("requirement_ids", sa.JSON(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("external_reference", sa.String(length=240), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_batch_id"], ["document_request_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_batch_id", name="uq_claim_correspondence_request_batch"),
    )
    op.create_index("ix_claim_correspondence_organization_id", "claim_correspondence", ["organization_id"], unique=False)
    op.create_index("ix_claim_correspondence_claim_id", "claim_correspondence", ["claim_id"], unique=False)
    op.create_index("ix_claim_correspondence_request_batch_id", "claim_correspondence", ["request_batch_id"], unique=False)
    op.create_index("ix_claim_correspondence_org_claim_created", "claim_correspondence", ["organization_id", "claim_id", "created_at"], unique=False)
    op.create_index("ix_claim_correspondence_org_claim_status", "claim_correspondence", ["organization_id", "claim_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_claim_correspondence_org_claim_status", table_name="claim_correspondence")
    op.drop_index("ix_claim_correspondence_org_claim_created", table_name="claim_correspondence")
    op.drop_index("ix_claim_correspondence_request_batch_id", table_name="claim_correspondence")
    op.drop_index("ix_claim_correspondence_claim_id", table_name="claim_correspondence")
    op.drop_index("ix_claim_correspondence_organization_id", table_name="claim_correspondence")
    op.drop_table("claim_correspondence")
    sa.Enum(name="correspondence_channel").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="correspondence_sensitivity").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="correspondence_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="correspondence_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="correspondence_direction").drop(op.get_bind(), checkfirst=True)
