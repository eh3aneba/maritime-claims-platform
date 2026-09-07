"""add governed claim domain classification lineage

Revision ID: 0084_claim_domain_classification
Revises: 0083_provider_live_activation
"""

from alembic import op
import sqlalchemy as sa

revision = "0084_claim_domain_classification"
down_revision = "0083_provider_live_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_domain_classifications",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_version", sa.String(length=32), nullable=False),
        sa.Column("classification_number", sa.Integer(), nullable=False),
        sa.Column("incident_code", sa.String(length=64), nullable=False),
        sa.Column("component_code", sa.String(length=64), nullable=True),
        sa.Column("failure_mode", sa.String(length=160), nullable=True),
        sa.Column("classification_note", sa.Text(), nullable=False),
        sa.Column("classified_by_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_classification_id", sa.Uuid(), nullable=True),
        sa.Column("previous_classification_hash", sa.String(length=64), nullable=True),
        sa.Column("classification_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["classified_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supersedes_classification_id"],
            ["claim_domain_classifications.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "claim_id",
            "classification_number",
            name="uq_claim_domain_classification_number",
        ),
        sa.UniqueConstraint("classification_hash", name="uq_claim_domain_classification_hash"),
    )
    op.create_index(
        "ix_claim_domain_classification_claim",
        "claim_domain_classifications",
        ["organization_id", "claim_id", "classification_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_domain_classifications_claim_id"),
        "claim_domain_classifications",
        ["claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_domain_classifications_organization_id"),
        "claim_domain_classifications",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_claim_domain_classifications_organization_id"), table_name="claim_domain_classifications")
    op.drop_index(op.f("ix_claim_domain_classifications_claim_id"), table_name="claim_domain_classifications")
    op.drop_index("ix_claim_domain_classification_claim", table_name="claim_domain_classifications")
    op.drop_table("claim_domain_classifications")
