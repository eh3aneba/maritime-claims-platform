"""design-partner rehearsal and readiness evidence

Revision ID: 0033_partner_rehearsal
Revises: 0032_pilot_governance
"""
import sqlalchemy as sa
from alembic import op

revision = "0033_partner_rehearsal"
down_revision = "0032_pilot_governance"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "design_partner_rehearsals",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("readiness_review_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True), sa.Column("completed_by_id", sa.Uuid(), nullable=True),
        sa.Column("rehearsal_key", sa.String(120), nullable=False), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=False), sa.Column("participant_roles", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), server_default="draft", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=True), sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["readiness_review_id"], ["deployment_readiness_reviews.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "rehearsal_key", name="uq_design_partner_rehearsal_key"),
    )
    op.create_index("ix_design_partner_rehearsals_organization_id", "design_partner_rehearsals", ["organization_id"])
    op.create_index("ix_design_partner_rehearsals_readiness_review_id", "design_partner_rehearsals", ["readiness_review_id"])
    op.create_index("ix_design_partner_rehearsal_org_status", "design_partner_rehearsals", ["organization_id", "status", "scheduled_for"])

    op.create_table(
        "rehearsal_control_evidence",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True), sa.Column("control_key", sa.String(50), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False), sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("result", sa.String(30), nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rehearsal_id"], ["design_partner_rehearsals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rehearsal_id", "control_key", name="uq_rehearsal_control_evidence"),
    )
    op.create_index("ix_rehearsal_control_evidence_organization_id", "rehearsal_control_evidence", ["organization_id"])
    op.create_index("ix_rehearsal_control_evidence_rehearsal_id", "rehearsal_control_evidence", ["rehearsal_id"])
    op.create_index("ix_rehearsal_evidence_org_rehearsal", "rehearsal_control_evidence", ["organization_id", "rehearsal_id"])

    op.create_table(
        "rehearsal_remediation_findings",
        sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True), sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True), sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_label", sa.String(180), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), server_default="open", nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rehearsal_id"], ["design_partner_rehearsals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["rehearsal_control_evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rehearsal_remediation_findings_organization_id", "rehearsal_remediation_findings", ["organization_id"])
    op.create_index("ix_rehearsal_remediation_findings_rehearsal_id", "rehearsal_remediation_findings", ["rehearsal_id"])
    op.create_index("ix_rehearsal_finding_org_status", "rehearsal_remediation_findings", ["organization_id", "rehearsal_id", "status"])


def downgrade() -> None:
    for table, indexes in [
        ("rehearsal_remediation_findings", ["ix_rehearsal_finding_org_status", "ix_rehearsal_remediation_findings_rehearsal_id", "ix_rehearsal_remediation_findings_organization_id"]),
        ("rehearsal_control_evidence", ["ix_rehearsal_evidence_org_rehearsal", "ix_rehearsal_control_evidence_rehearsal_id", "ix_rehearsal_control_evidence_organization_id"]),
        ("design_partner_rehearsals", ["ix_design_partner_rehearsal_org_status", "ix_design_partner_rehearsals_readiness_review_id", "ix_design_partner_rehearsals_organization_id"]),
    ]:
        for index in indexes: op.drop_index(index, table_name=table)
        op.drop_table(table)
