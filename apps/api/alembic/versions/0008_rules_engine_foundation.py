"""rules engine and missing document foundation

Revision ID: 0008_rules_engine_foundation
Revises: 0007_chronology_conflicts
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_rules_engine_foundation"
down_revision: Union[str, None] = "0007_chronology_conflicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    req_priority = postgresql.ENUM("critical", "important", "supporting", name="requirement_priority", create_type=False)
    req_status = postgresql.ENUM("missing", "requested", "received", "under_review", "accepted", "rejected", "superseded", "not_required", name="requirement_status", create_type=False)
    issue_category = postgresql.ENUM("technical", "insurance", "financial", "evidence", "operational", "workflow", name="claim_issue_category", create_type=False)
    issue_severity = postgresql.ENUM("low", "medium", "high", "critical", name="claim_issue_severity", create_type=False)
    issue_status = postgresql.ENUM("open", "under_review", "resolved", "dismissed", name="claim_issue_status", create_type=False)
    for enum_type in (req_priority, req_status, issue_category, issue_severity, issue_status):
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "claim_document_requirements",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matched_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=30), server_default="1.0", nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("document_label", sa.String(length=180), nullable=False),
        sa.Column("priority", req_priority, nullable=False),
        sa.Column("required_from_status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", req_status, server_default="missing", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["matched_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "rule_id", "document_type", name="uq_claim_doc_req_rule_type"),
    )
    op.create_index("ix_claim_document_requirements_organization_id", "claim_document_requirements", ["organization_id"])
    op.create_index("ix_claim_document_requirements_claim_id", "claim_document_requirements", ["claim_id"])
    op.create_index("ix_claim_doc_req_org_claim_active", "claim_document_requirements", ["organization_id", "claim_id", "is_active"])
    op.create_index("ix_claim_doc_req_status", "claim_document_requirements", ["organization_id", "status"])

    op.create_table(
        "claim_issues",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_key", sa.String(length=100), nullable=False),
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=30), server_default="1.0", nullable=False),
        sa.Column("category", issue_category, nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", issue_severity, nullable=False),
        sa.Column("status", issue_status, server_default="open", nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "issue_key", name="uq_claim_issue_key"),
    )
    op.create_index("ix_claim_issues_organization_id", "claim_issues", ["organization_id"])
    op.create_index("ix_claim_issues_claim_id", "claim_issues", ["claim_id"])
    op.create_index("ix_claim_issues_org_claim_active", "claim_issues", ["organization_id", "claim_id", "is_active"])
    op.create_index("ix_claim_issues_status", "claim_issues", ["organization_id", "status"])

    op.create_table(
        "rule_evaluation_runs",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ruleset_name", sa.String(length=100), server_default="hm_machinery_rules", nullable=False),
        sa.Column("ruleset_version", sa.String(length=30), server_default="1.0", nullable=False),
        sa.Column("trigger", sa.String(length=50), server_default="manual", nullable=False),
        sa.Column("triggered_rule_ids", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evaluated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_evaluation_runs_organization_id", "rule_evaluation_runs", ["organization_id"])
    op.create_index("ix_rule_evaluation_runs_claim_id", "rule_evaluation_runs", ["claim_id"])
    op.create_index("ix_rule_runs_org_claim_created", "rule_evaluation_runs", ["organization_id", "claim_id", "created_at"])


def downgrade() -> None:
    op.drop_table("rule_evaluation_runs")
    op.drop_table("claim_issues")
    op.drop_table("claim_document_requirements")
    op.execute("DROP TYPE claim_issue_status")
    op.execute("DROP TYPE claim_issue_severity")
    op.execute("DROP TYPE claim_issue_category")
    op.execute("DROP TYPE requirement_status")
    op.execute("DROP TYPE requirement_priority")
