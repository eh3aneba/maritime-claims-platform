"""consent-gated controlled email ingestion

Revision ID: 0026_controlled_email_ingestion
Revises: 0025_settlement_payment_ledger
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_controlled_email_ingestion"
down_revision = "0025_settlement_payment_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection_status = sa.Enum("active", "suspended", "revoked", name="email_connection_status")
    message_status = sa.Enum("pending_review", "linked", "rejected", "expired", name="email_message_status")
    op.create_table(
        "email_ingestion_connections",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("provider_label", sa.String(80), nullable=False), sa.Column("mailbox_address", sa.String(320), nullable=False),
        sa.Column("status", connection_status, server_default="active", nullable=False), sa.Column("consent_basis", sa.Text(), nullable=False),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "mailbox_address", name="uq_email_connection_org_mailbox"),
    )
    op.create_index("ix_email_ingestion_connections_organization_id", "email_ingestion_connections", ["organization_id"])
    op.create_index("ix_email_connection_org_status", "email_ingestion_connections", ["organization_id", "status"])
    op.create_table(
        "ingested_email_messages",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("suggested_claim_id", sa.Uuid(), nullable=True), sa.Column("linked_claim_id", sa.Uuid(), nullable=True),
        sa.Column("linked_by_id", sa.Uuid(), nullable=True), sa.Column("correspondence_id", sa.Uuid(), nullable=True),
        sa.Column("provider_message_id", sa.String(240), nullable=False), sa.Column("internet_message_id", sa.String(500), nullable=True),
        sa.Column("sender", sa.String(500), nullable=False), sa.Column("recipients", sa.JSON(), nullable=False), sa.Column("cc", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False), sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", message_status, server_default="pending_review", nullable=False), sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True), sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False), sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connection_id"], ["email_ingestion_connections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["suggested_claim_id"], ["claims.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_claim_id"], ["claims.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["correspondence_id"], ["claim_correspondence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("connection_id", "provider_message_id", name="uq_ingested_email_provider_message"),
    )
    for name, cols in [
        ("ix_ingested_email_messages_organization_id", ["organization_id"]), ("ix_ingested_email_messages_connection_id", ["connection_id"]),
        ("ix_ingested_email_messages_suggested_claim_id", ["suggested_claim_id"]), ("ix_ingested_email_messages_linked_claim_id", ["linked_claim_id"]),
        ("ix_ingested_email_messages_retain_until", ["retain_until"]), ("ix_ingested_email_org_status_received", ["organization_id", "status", "received_at"]),
    ]: op.create_index(name, "ingested_email_messages", cols)
    op.create_table(
        "email_attachment_manifests",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False), sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False), sa.Column("provider_sha256", sa.String(64), nullable=True),
        sa.Column("admission_status", sa.String(60), server_default="blocked_pending_quarantine", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["ingested_email_messages.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_attachment_manifests_organization_id", "email_attachment_manifests", ["organization_id"])
    op.create_index("ix_email_attachment_manifests_message_id", "email_attachment_manifests", ["message_id"])
    op.create_index("ix_email_attachment_message", "email_attachment_manifests", ["message_id", "created_at"])


def downgrade() -> None:
    for name in ["ix_email_attachment_message", "ix_email_attachment_manifests_message_id", "ix_email_attachment_manifests_organization_id"]: op.drop_index(name, table_name="email_attachment_manifests")
    op.drop_table("email_attachment_manifests")
    for name in ["ix_ingested_email_org_status_received", "ix_ingested_email_messages_retain_until", "ix_ingested_email_messages_linked_claim_id", "ix_ingested_email_messages_suggested_claim_id", "ix_ingested_email_messages_connection_id", "ix_ingested_email_messages_organization_id"]: op.drop_index(name, table_name="ingested_email_messages")
    op.drop_table("ingested_email_messages")
    for name in ["ix_email_connection_org_status", "ix_email_ingestion_connections_organization_id"]: op.drop_index(name, table_name="email_ingestion_connections")
    op.drop_table("email_ingestion_connections")
    sa.Enum(name="email_message_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="email_connection_status").drop(op.get_bind(), checkfirst=True)
