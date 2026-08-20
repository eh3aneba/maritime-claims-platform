"""operational monitoring and incident response

Revision ID: 0030_operational_monitoring
Revises: 0029_deployment_readiness
"""
import sqlalchemy as sa
from alembic import op

revision = "0030_operational_monitoring"
down_revision = "0029_deployment_readiness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_monitor_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("initiated_by_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("alerts", sa.JSON(), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initiated_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_operational_monitor_run_key"),
    )
    op.create_index("ix_operational_monitor_runs_organization_id", "operational_monitor_runs", ["organization_id"])
    op.create_index("ix_operational_monitor_org_run", "operational_monitor_runs", ["organization_id", "run_at"])
    op.create_table(
        "operational_incidents",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("monitor_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True), sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False), sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("owner_label", sa.String(180), nullable=False), sa.Column("status", sa.String(30), server_default="open", nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True), sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["monitor_run_id"], ["operational_monitor_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operational_incidents_organization_id", "operational_incidents", ["organization_id"])
    op.create_index("ix_operational_incident_org_status_severity", "operational_incidents", ["organization_id", "status", "severity"])


def downgrade() -> None:
    op.drop_index("ix_operational_incident_org_status_severity", table_name="operational_incidents")
    op.drop_index("ix_operational_incidents_organization_id", table_name="operational_incidents"); op.drop_table("operational_incidents")
    op.drop_index("ix_operational_monitor_org_run", table_name="operational_monitor_runs")
    op.drop_index("ix_operational_monitor_runs_organization_id", table_name="operational_monitor_runs"); op.drop_table("operational_monitor_runs")
