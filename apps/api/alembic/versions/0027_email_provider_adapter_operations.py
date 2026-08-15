"""least-privilege email provider adapter operations

Revision ID: 0027_email_provider_adapters
Revises: 0026_controlled_email_ingestion
"""
import sqlalchemy as sa
from alembic import op

revision = "0027_email_provider_adapters"
down_revision = "0026_controlled_email_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_provider_adapters",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True), sa.Column("provider_kind", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False), sa.Column("credential_reference", sa.String(240), nullable=False),
        sa.Column("allowed_folder", sa.String(240), nullable=False), sa.Column("permission_manifest", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), server_default="active", nullable=False), sa.Column("batch_limit", sa.Integer(), server_default="50", nullable=False),
        sa.Column("retention_schedule_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True), sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_hash", sa.String(64), nullable=True), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connection_id"], ["email_ingestion_connections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", name="uq_email_provider_adapter_connection"),
    )
    for name, cols in [("ix_email_provider_adapters_organization_id", ["organization_id"]),
                       ("ix_email_provider_adapters_connection_id", ["connection_id"]),
                       ("ix_email_provider_adapters_next_sync_at", ["next_sync_at"]),
                       ("ix_email_provider_adapter_org_status", ["organization_id", "status"])]:
        op.create_index(name, "email_provider_adapters", cols)
    op.create_table(
        "email_adapter_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("adapter_id", sa.Uuid(), nullable=False),
        sa.Column("initiated_by_id", sa.Uuid(), nullable=True), sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("messages_seen", sa.Integer(), server_default="0", nullable=False), sa.Column("messages_ingested", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checkpoint_hash", sa.String(64), nullable=True), sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["adapter_id"], ["email_provider_adapters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("adapter_id", "idempotency_key", name="uq_email_adapter_run_idempotency"),
    )
    for name, cols in [("ix_email_adapter_runs_organization_id", ["organization_id"]),
                       ("ix_email_adapter_runs_adapter_id", ["adapter_id"]),
                       ("ix_email_adapter_run_org_started", ["organization_id", "started_at"])]:
        op.create_index(name, "email_adapter_runs", cols)
    op.create_table(
        "email_retention_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("initiated_by_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("expired_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_email_retention_run_idempotency"),
    )
    op.create_index("ix_email_retention_runs_organization_id", "email_retention_runs", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_email_retention_runs_organization_id", table_name="email_retention_runs"); op.drop_table("email_retention_runs")
    for name in ["ix_email_adapter_run_org_started", "ix_email_adapter_runs_adapter_id", "ix_email_adapter_runs_organization_id"]:
        op.drop_index(name, table_name="email_adapter_runs")
    op.drop_table("email_adapter_runs")
    for name in ["ix_email_provider_adapter_org_status", "ix_email_provider_adapters_next_sync_at", "ix_email_provider_adapters_connection_id", "ix_email_provider_adapters_organization_id"]:
        op.drop_index(name, table_name="email_provider_adapters")
    op.drop_table("email_provider_adapters")
