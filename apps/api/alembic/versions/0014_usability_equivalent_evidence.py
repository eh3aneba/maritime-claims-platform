"""Usability hardening: equivalent evidence provenance for document requirements.

Revision ID: 0014_usability_hardening
Revises: 0013_pilot_hardening
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_usability_hardening"
down_revision: Union[str, None] = "0013_pilot_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claim_document_requirements", sa.Column("equivalent_claim_fact_id", sa.Uuid(), nullable=True))
    op.add_column("claim_document_requirements", sa.Column("satisfied_by_id", sa.Uuid(), nullable=True))
    op.add_column("claim_document_requirements", sa.Column("satisfaction_basis", sa.String(length=50), nullable=True))
    op.add_column("claim_document_requirements", sa.Column("satisfaction_note", sa.Text(), nullable=True))
    op.add_column("claim_document_requirements", sa.Column("satisfied_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_claim_doc_req_equivalent_fact",
        "claim_document_requirements",
        "claim_facts",
        ["equivalent_claim_fact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_claim_doc_req_satisfied_by",
        "claim_document_requirements",
        "users",
        ["satisfied_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_claim_doc_req_satisfied_by", "claim_document_requirements", type_="foreignkey")
    op.drop_constraint("fk_claim_doc_req_equivalent_fact", "claim_document_requirements", type_="foreignkey")
    op.drop_column("claim_document_requirements", "satisfied_at")
    op.drop_column("claim_document_requirements", "satisfaction_note")
    op.drop_column("claim_document_requirements", "satisfaction_basis")
    op.drop_column("claim_document_requirements", "satisfied_by_id")
    op.drop_column("claim_document_requirements", "equivalent_claim_fact_id")
