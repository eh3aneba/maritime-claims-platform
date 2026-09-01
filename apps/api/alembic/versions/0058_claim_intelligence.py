"""Claims intelligence engine

Revision ID: 0058_claim_intelligence
Revises: 0057_ai_production_wide
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_claim_intelligence"
down_revision = "0057_ai_production_wide"
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "claim_intelligence_snapshots",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("generated_by_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.String(40), server_default="12A.1", nullable=False),
        sa.Column("source_state_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "snapshot_version", name="uq_ci_snapshot_version"),
        sa.UniqueConstraint("organization_id", "claim_id", "source_state_hash", name="uq_ci_source_state"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_ci_snapshot_version"),
    )
    op.create_index("ix_ci_snapshot_claim", "claim_intelligence_snapshots", ["organization_id", "claim_id", "snapshot_version"])

    op.create_table(
        "claim_intelligence_items",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.String(120), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("urgency_score", sa.Integer(), nullable=False),
        sa.Column("evidential_value_score", sa.Integer(), nullable=False),
        sa.Column("rank_score", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("related_entity_type", sa.String(60), nullable=True),
        sa.Column("related_entity_id", sa.Uuid(), nullable=True),
        sa.Column("item_hash", sa.String(64), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["claim_intelligence_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "item_key", name="uq_ci_item_key"),
        sa.CheckConstraint("category IN ('incident_summary','chronology','machinery_context','evidence_available','missing_evidence','conflict','hypothesis','issue_flag','financial_lead','recovery_lead','deadline_lead','next_action')", name="ck_ci_item_category"),
        sa.CheckConstraint("severity IN ('info','low','medium','high','critical')", name="ck_ci_item_severity"),
        sa.CheckConstraint("urgency_score BETWEEN 0 AND 100", name="ck_ci_item_urgency"),
        sa.CheckConstraint("evidential_value_score BETWEEN 0 AND 100", name="ck_ci_item_evidence"),
        sa.CheckConstraint("rank_score BETWEEN 0 AND 100", name="ck_ci_item_rank"),
    )
    op.create_index("ix_ci_item_snapshot", "claim_intelligence_items", ["organization_id", "claim_id", "snapshot_id", "category"])
    op.create_index("ix_ci_item_rank", "claim_intelligence_items", ["snapshot_id", "rank_score"])

    op.create_table(
        "claim_intelligence_item_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("converted_task_id", sa.Uuid(), nullable=True),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("edited_title", sa.String(240), nullable=True),
        sa.Column("edited_description", sa.Text(), nullable=True),
        sa.Column("edited_suggested_action", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("previous_decision_hash", sa.String(64), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["claim_intelligence_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["converted_task_id"], ["claim_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "decision_number", name="uq_ci_decision_number"),
        sa.CheckConstraint("decision_number >= 1", name="ck_ci_decision_number"),
        sa.CheckConstraint("action IN ('accept','edit','dismiss')", name="ck_ci_decision_action"),
    )
    op.create_index("ix_ci_decision_item", "claim_intelligence_item_decisions", ["organization_id", "claim_id", "item_id", "decision_number"])


def downgrade() -> None:
    op.drop_index("ix_ci_decision_item", table_name="claim_intelligence_item_decisions")
    op.drop_table("claim_intelligence_item_decisions")
    op.drop_index("ix_ci_item_rank", table_name="claim_intelligence_items")
    op.drop_index("ix_ci_item_snapshot", table_name="claim_intelligence_items")
    op.drop_table("claim_intelligence_items")
    op.drop_index("ix_ci_snapshot_claim", table_name="claim_intelligence_snapshots")
    op.drop_table("claim_intelligence_snapshots")
