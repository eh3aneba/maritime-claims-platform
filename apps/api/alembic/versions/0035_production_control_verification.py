"""production control evidence and independent verification gate

Revision ID: 0035_control_verification
Revises: 0034_pilot_architecture
"""
import sqlalchemy as sa
from alembic import op

revision = "0035_control_verification"
down_revision = "0034_pilot_architecture"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "production_control_verification_gates",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("architecture_baseline_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("completed_by_id", sa.Uuid(), nullable=True),
        sa.Column("gate_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), server_default="collecting", nullable=False),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("outcome_hash", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["architecture_baseline_id"], ["production_architecture_baselines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "gate_key", name="uq_production_control_gate_key"),
        sa.UniqueConstraint("architecture_baseline_id", name="uq_production_control_gate_baseline"),
    )
    op.create_index("ix_production_control_verification_gates_organization_id", "production_control_verification_gates", ["organization_id"])
    op.create_index("ix_production_control_verification_gates_architecture_baseline_id", "production_control_verification_gates", ["architecture_baseline_id"])
    op.create_index("ix_production_control_gate_org_status", "production_control_verification_gates", ["organization_id", "status", "created_at"])

    op.create_table(
        "production_control_evidence",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("control_key", sa.String(50), nullable=False),
        sa.Column("submission_version", sa.Integer(), nullable=False),
        sa.Column("implementation_summary", sa.Text(), nullable=False),
        sa.Column("verification_method", sa.Text(), nullable=False),
        sa.Column("rollback_plan", sa.Text(), nullable=False),
        sa.Column("owner_label", sa.String(180), nullable=False),
        sa.Column("implementation_completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), server_default="submitted", nullable=False),
        sa.Column("review_reference", sa.String(500), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gate_id"], ["production_control_verification_gates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gate_id", "control_key", "submission_version", name="uq_production_control_evidence_version"),
        sa.CheckConstraint("submission_version >= 1", name="ck_production_control_evidence_version"),
    )
    op.create_index("ix_production_control_evidence_organization_id", "production_control_evidence", ["organization_id"])
    op.create_index("ix_production_control_evidence_gate_id", "production_control_evidence", ["gate_id"])
    op.create_index("ix_production_control_evidence_org_gate", "production_control_evidence", ["organization_id", "gate_id", "control_key"])


def downgrade() -> None:
    for index in ["ix_production_control_evidence_org_gate", "ix_production_control_evidence_gate_id", "ix_production_control_evidence_organization_id"]:
        op.drop_index(index, table_name="production_control_evidence")
    op.drop_table("production_control_evidence")
    for index in ["ix_production_control_gate_org_status", "ix_production_control_verification_gates_architecture_baseline_id", "ix_production_control_verification_gates_organization_id"]:
        op.drop_index(index, table_name="production_control_verification_gates")
    op.drop_table("production_control_verification_gates")
