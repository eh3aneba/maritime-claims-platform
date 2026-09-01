"""Signed content-free governance webhooks and delivery ledger

Revision ID: 0064_governance_webhooks
Revises: 0063_claim_qa_synthesis
"""
import sqlalchemy as sa
from alembic import op

revision = "0064_governance_webhooks"
down_revision = "0063_claim_qa_synthesis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "governance_webhook_destinations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("event_types", sa.JSON(), nullable=False),
        sa.Column("secret_salt", sa.String(length=64), nullable=False),
        sa.Column("secret_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("secret_reference", sa.String(length=180), nullable=False),
        sa.Column("previous_secret_salt", sa.String(length=64), nullable=True),
        sa.Column("previous_secret_version", sa.Integer(), nullable=True),
        sa.Column("previous_secret_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_gwd_org_name"),
    )
    op.create_index(
        "ix_gwd_org_enabled",
        "governance_webhook_destinations",
        ["organization_id", "enabled", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_governance_webhook_destinations_organization_id"),
        "governance_webhook_destinations",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "governance_webhook_deliveries",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("source_workflow_type", sa.String(length=60), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_hash", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("envelope_version", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("secret_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="6", nullable=False),
        sa.Column("manual_retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["destination_id"], ["governance_webhook_destinations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "destination_id",
            "source_workflow_type",
            "source_event_id",
            "source_revision_hash",
            "envelope_version",
            name="uq_gwdel_source_revision",
        ),
    )
    op.create_index(
        "ix_gwdel_org_status",
        "governance_webhook_deliveries",
        ["organization_id", "status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_gwdel_destination",
        "governance_webhook_deliveries",
        ["destination_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_governance_webhook_deliveries_organization_id"),
        "governance_webhook_deliveries",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_governance_webhook_deliveries_destination_id"),
        "governance_webhook_deliveries",
        ["destination_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_governance_webhook_deliveries_destination_id"),
        table_name="governance_webhook_deliveries",
    )
    op.drop_index(
        op.f("ix_governance_webhook_deliveries_organization_id"),
        table_name="governance_webhook_deliveries",
    )
    op.drop_index("ix_gwdel_destination", table_name="governance_webhook_deliveries")
    op.drop_index("ix_gwdel_org_status", table_name="governance_webhook_deliveries")
    op.drop_table("governance_webhook_deliveries")
    op.drop_index(
        op.f("ix_governance_webhook_destinations_organization_id"),
        table_name="governance_webhook_destinations",
    )
    op.drop_index("ix_gwd_org_enabled", table_name="governance_webhook_destinations")
    op.drop_table("governance_webhook_destinations")
