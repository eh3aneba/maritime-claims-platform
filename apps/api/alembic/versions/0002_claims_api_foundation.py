"""claims api foundation

Revision ID: 0002_claims_api_foundation
Revises: 0001_database_foundation
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_claims_api_foundation"
down_revision: Union[str, None] = "0001_database_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

claim_type_existing = postgresql.ENUM("hull_machinery", name="claim_type", create_type=False)


def upgrade() -> None:
    # Keep claim amounts valid at the database boundary as well as in Pydantic.
    op.create_check_constraint(
        "ck_claims_estimated_loss_nonnegative", "claims", "estimated_loss IS NULL OR estimated_loss >= 0"
    )
    op.create_check_constraint(
        "ck_claims_reserve_nonnegative", "claims", "current_reserve IS NULL OR current_reserve >= 0"
    )

    op.create_table(
        "claim_reference_sequences",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("claim_type", claim_type_existing, nullable=False),
        sa.Column("last_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("year >= 2000 AND year <= 2200", name="ck_claim_ref_seq_year"),
        sa.CheckConstraint("last_number >= 0", name="ck_claim_ref_seq_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "year", "claim_type", name="uq_claim_ref_seq_org_year_type"),
    )
    op.create_index(
        "ix_claim_reference_sequences_organization_id",
        "claim_reference_sequences",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_claim_reference_sequences_organization_id", table_name="claim_reference_sequences")
    op.drop_table("claim_reference_sequences")
    op.drop_constraint("ck_claims_reserve_nonnegative", "claims", type_="check")
    op.drop_constraint("ck_claims_estimated_loss_nonnegative", "claims", type_="check")
