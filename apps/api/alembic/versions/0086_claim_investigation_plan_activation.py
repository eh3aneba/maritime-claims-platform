"""add explicit investigation plan activation and task provenance

Revision ID: 0086_claim_investigation_plan_activation
Revises: 0085_claim_investigation_plan
"""

from alembic import op
import sqlalchemy as sa

revision = "0086_claim_investigation_plan_activation"
down_revision = "0085_claim_investigation_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_investigation_plan_activations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("activation_number", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_number", sa.Integer(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("selected_items", sa.JSON(), nullable=False),
        sa.Column("activation_note", sa.Text(), nullable=False),
        sa.Column("activated_by_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("previous_activation_hash", sa.String(length=64), nullable=True),
        sa.Column("activation_key_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_hash", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["claim_investigation_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "claim_id", "activation_number", name="uq_claim_investigation_activation_number"
        ),
        sa.UniqueConstraint(
            "organization_id", "claim_id", "activation_key_hash", name="uq_claim_investigation_activation_key"
        ),
        sa.UniqueConstraint("activation_hash", name="uq_claim_investigation_activation_hash"),
    )
    op.create_index(
        "ix_claim_investigation_activation_claim",
        "claim_investigation_plan_activations",
        ["organization_id", "claim_id", "activation_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_investigation_plan_activations_organization_id"),
        "claim_investigation_plan_activations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_investigation_plan_activations_claim_id"),
        "claim_investigation_plan_activations",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_investigation_plan_activations_plan_id"),
        "claim_investigation_plan_activations",
        ["plan_id"],
        unique=False,
    )

    op.add_column("claim_tasks", sa.Column("investigation_plan_id", sa.Uuid(), nullable=True))
    op.add_column("claim_tasks", sa.Column("investigation_activation_id", sa.Uuid(), nullable=True))
    op.add_column("claim_tasks", sa.Column("investigation_item_key", sa.String(length=80), nullable=True))
    op.create_foreign_key(
        "fk_claim_tasks_investigation_plan_id",
        "claim_tasks",
        "claim_investigation_plans",
        ["investigation_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_claim_tasks_investigation_activation_id",
        "claim_tasks",
        "claim_investigation_plan_activations",
        ["investigation_activation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_claim_tasks_investigation_plan_id"), "claim_tasks", ["investigation_plan_id"], unique=False)
    op.create_index(
        op.f("ix_claim_tasks_investigation_activation_id"),
        "claim_tasks",
        ["investigation_activation_id"],
        unique=False,
    )
    op.create_index(
        "ix_claim_tasks_investigation_plan",
        "claim_tasks",
        ["organization_id", "claim_id", "investigation_plan_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_claim_task_investigation_plan_item",
        "claim_tasks",
        ["investigation_plan_id", "investigation_item_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_claim_task_investigation_plan_item", "claim_tasks", type_="unique")
    op.drop_index("ix_claim_tasks_investigation_plan", table_name="claim_tasks")
    op.drop_index(op.f("ix_claim_tasks_investigation_activation_id"), table_name="claim_tasks")
    op.drop_index(op.f("ix_claim_tasks_investigation_plan_id"), table_name="claim_tasks")
    op.drop_constraint("fk_claim_tasks_investigation_activation_id", "claim_tasks", type_="foreignkey")
    op.drop_constraint("fk_claim_tasks_investigation_plan_id", "claim_tasks", type_="foreignkey")
    op.drop_column("claim_tasks", "investigation_item_key")
    op.drop_column("claim_tasks", "investigation_activation_id")
    op.drop_column("claim_tasks", "investigation_plan_id")

    op.drop_index(op.f("ix_claim_investigation_plan_activations_plan_id"), table_name="claim_investigation_plan_activations")
    op.drop_index(op.f("ix_claim_investigation_plan_activations_claim_id"), table_name="claim_investigation_plan_activations")
    op.drop_index(op.f("ix_claim_investigation_plan_activations_organization_id"), table_name="claim_investigation_plan_activations")
    op.drop_index("ix_claim_investigation_activation_claim", table_name="claim_investigation_plan_activations")
    op.drop_table("claim_investigation_plan_activations")
