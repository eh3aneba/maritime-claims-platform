"""operational acceptance and bounded go-live authorization

Revision ID: 0037_operational_acceptance
Revises: 0036_control_scope
"""
import sqlalchemy as sa
from alembic import op

revision = "0037_operational_acceptance"
down_revision = "0036_control_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_acceptances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("control_verification_gate_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("acceptance_key", sa.String(120), nullable=False),
        sa.Column("release_identifier", sa.String(160), nullable=False),
        sa.Column("target_environment", sa.String(30), server_default="production", nullable=False),
        sa.Column("change_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_owner_label", sa.String(180), nullable=False),
        sa.Column("rollback_owner_label", sa.String(180), nullable=False),
        sa.Column("incident_commander_label", sa.String(180), nullable=False),
        sa.Column("support_owner_label", sa.String(180), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_approvals", nullable=False),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["control_verification_gate_id"],
                                ["production_control_verification_gates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "acceptance_key",
                            name="uq_operational_acceptance_key"),
        sa.UniqueConstraint("control_verification_gate_id", "attempt_number",
                            name="uq_operational_acceptance_attempt"),
    )
    op.create_index("ix_operational_acceptance_org_status", "operational_acceptances",
                    ["organization_id", "status", "created_at"])
    op.create_index(op.f("ix_operational_acceptances_organization_id"),
                    "operational_acceptances", ["organization_id"])
    op.create_index(op.f("ix_operational_acceptances_control_verification_gate_id"),
                    "operational_acceptances", ["control_verification_gate_id"])

    op.create_table(
        "operational_acceptance_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("check_key", sa.String(50), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("owner_label", sa.String(180), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["acceptance_id"], ["operational_acceptances.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("acceptance_id", "check_key",
                            name="uq_operational_acceptance_check"),
    )
    op.create_index("ix_operational_acceptance_check_org", "operational_acceptance_checks",
                    ["organization_id", "acceptance_id", "result"])
    op.create_index(op.f("ix_operational_acceptance_checks_organization_id"),
                    "operational_acceptance_checks", ["organization_id"])
    op.create_index(op.f("ix_operational_acceptance_checks_acceptance_id"),
                    "operational_acceptance_checks", ["acceptance_id"])

    op.create_table(
        "operational_acceptance_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approval_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["acceptance_id"], ["operational_acceptances.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("acceptance_id", "approval_role",
                            name="uq_operational_acceptance_role"),
    )
    op.create_index("ix_operational_acceptance_approval_org",
                    "operational_acceptance_approvals", ["organization_id", "acceptance_id"])
    op.create_index(op.f("ix_operational_acceptance_approvals_organization_id"),
                    "operational_acceptance_approvals", ["organization_id"])
    op.create_index(op.f("ix_operational_acceptance_approvals_acceptance_id"),
                    "operational_acceptance_approvals", ["acceptance_id"])


def downgrade() -> None:
    op.drop_table("operational_acceptance_approvals")
    op.drop_table("operational_acceptance_checks")
    op.drop_table("operational_acceptances")
