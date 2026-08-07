"""rule driven tasks and document request drafts

Revision ID: 0009_rule_driven_tasks
Revises: 0008_rules_engine_foundation
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_rule_driven_tasks"
down_revision: Union[str, None] = "0008_rules_engine_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    task_type = postgresql.ENUM("document_request", "review", "follow_up", name="claim_task_type", create_type=False)
    task_status = postgresql.ENUM("open", "completed", "cancelled", name="claim_task_status", create_type=False)
    task_priority = postgresql.ENUM("low", "medium", "high", "critical", name="claim_task_priority", create_type=False)
    task_source = postgresql.ENUM("human", "rule", "ai_suggestion", name="claim_task_source", create_type=False)
    batch_status = postgresql.ENUM("draft", "sent_externally", "cancelled", name="document_request_batch_status", create_type=False)
    for enum_type in (task_type, task_status, task_priority, task_source, batch_status):
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "document_request_batches",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_label", sa.String(length=180), nullable=True),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("draft_body", sa.Text(), nullable=False),
        sa.Column("requirement_ids", sa.JSON(), nullable=False),
        sa.Column("status", batch_status, server_default="draft", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_request_batches_organization_id", "document_request_batches", ["organization_id"])
    op.create_index("ix_document_request_batches_claim_id", "document_request_batches", ["claim_id"])
    op.create_index("ix_doc_request_batches_org_claim", "document_request_batches", ["organization_id", "claim_id", "created_at"])

    op.create_table(
        "claim_tasks",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("status", task_status, server_default="open", nullable=False),
        sa.Column("priority", task_priority, server_default="medium", nullable=False),
        sa.Column("source", task_source, server_default="human", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_reason", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_batch_id"], ["document_request_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requirement_id"], ["claim_document_requirements.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("organization_id", "claim_id", "requirement_id", "request_batch_id", "assignee_id"):
        op.create_index(f"ix_claim_tasks_{col}", "claim_tasks", [col])
    op.create_index("ix_claim_tasks_org_claim_status", "claim_tasks", ["organization_id", "claim_id", "status"])
    op.create_index("ix_claim_tasks_assignee_due", "claim_tasks", ["organization_id", "assignee_id", "due_date"])


def downgrade() -> None:
    op.drop_table("claim_tasks")
    op.drop_table("document_request_batches")
    op.execute("DROP TYPE document_request_batch_status")
    op.execute("DROP TYPE claim_task_source")
    op.execute("DROP TYPE claim_task_priority")
    op.execute("DROP TYPE claim_task_status")
    op.execute("DROP TYPE claim_task_type")
