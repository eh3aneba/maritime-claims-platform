"""add governed claim investigation plan lineage

Revision ID: 0085_claim_investigation_plan
Revises: 0084_claim_domain_classification
"""

from alembic import op
import sqlalchemy as sa

revision = "0085_claim_investigation_plan"
down_revision = "0084_claim_domain_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_investigation_plans",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("plan_number", sa.Integer(), nullable=False),
        sa.Column("classification_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_version", sa.String(length=32), nullable=False),
        sa.Column("classification_number", sa.Integer(), nullable=False),
        sa.Column("classification_hash", sa.String(length=64), nullable=False),
        sa.Column("registry_version", sa.String(length=32), nullable=False),
        sa.Column("registry_hash", sa.String(length=64), nullable=False),
        sa.Column("incident_code", sa.String(length=64), nullable=False),
        sa.Column("component_code", sa.String(length=64), nullable=True),
        sa.Column("failure_mode", sa.String(length=160), nullable=True),
        sa.Column("investigation_tracks", sa.JSON(), nullable=False),
        sa.Column("evidence_prompts", sa.JSON(), nullable=False),
        sa.Column("review_topics", sa.JSON(), nullable=False),
        sa.Column("contextual_rule_ids", sa.JSON(), nullable=False),
        sa.Column("adoption_note", sa.Text(), nullable=False),
        sa.Column("adopted_by_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_plan_id", sa.Uuid(), nullable=True),
        sa.Column("previous_plan_hash", sa.String(length=64), nullable=True),
        sa.Column("adoption_key_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["classification_id"], ["claim_domain_classifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["adopted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_plan_id"], ["claim_investigation_plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "plan_number",
            name="uq_claim_investigation_plan_number",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "adoption_key_hash",
            name="uq_claim_investigation_plan_adoption",
        ),
        sa.UniqueConstraint("plan_hash", name="uq_claim_investigation_plan_hash"),
    )
    op.create_index(
        "ix_claim_investigation_plan_claim",
        "claim_investigation_plans",
        ["organization_id", "claim_id", "plan_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_investigation_plans_organization_id"),
        "claim_investigation_plans",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_investigation_plans_claim_id"),
        "claim_investigation_plans",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_investigation_plans_classification_id"),
        "claim_investigation_plans",
        ["classification_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_claim_investigation_plans_classification_id"), table_name="claim_investigation_plans")
    op.drop_index(op.f("ix_claim_investigation_plans_claim_id"), table_name="claim_investigation_plans")
    op.drop_index(op.f("ix_claim_investigation_plans_organization_id"), table_name="claim_investigation_plans")
    op.drop_index("ix_claim_investigation_plan_claim", table_name="claim_investigation_plans")
    op.drop_table("claim_investigation_plans")
