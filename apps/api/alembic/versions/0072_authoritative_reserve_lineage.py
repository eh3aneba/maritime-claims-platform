"""Add authoritative reserve lineage and provenance controls.

Revision ID: 0072_authoritative_reserve_lineage
Revises: 0071_adjustment_source_state_controls
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0072_authoritative_reserve_lineage"
down_revision = "0071_adjustment_source_state_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reserve_history", sa.Column("sequence", sa.Integer(), nullable=True))
    op.add_column("reserve_history", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
    op.add_column("reserve_history", sa.Column("request_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "reserve_history",
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="legacy_unbound"),
    )
    op.add_column("reserve_history", sa.Column("source_reference_id", sa.Uuid(), nullable=True))
    op.add_column("reserve_history", sa.Column("source_state_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "reserve_history",
        sa.Column("source_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column("reserve_history", sa.Column("previous_reserve_hash", sa.String(length=64), nullable=True))
    op.add_column("reserve_history", sa.Column("reserve_hash", sa.String(length=64), nullable=True))

    op.create_unique_constraint(
        "uq_reserve_history_claim_sequence",
        "reserve_history",
        ["organization_id", "claim_id", "sequence"],
    )
    op.create_unique_constraint(
        "uq_reserve_history_claim_idempotency",
        "reserve_history",
        ["organization_id", "claim_id", "idempotency_key"],
    )
    op.create_index(
        "ix_reserve_history_org_claim_sequence",
        "reserve_history",
        ["organization_id", "claim_id", "sequence"],
    )
    op.create_index("ix_reserve_history_reserve_hash", "reserve_history", ["reserve_hash"])
    op.create_check_constraint(
        "ck_reserve_history_sequence_positive",
        "reserve_history",
        "sequence IS NULL OR sequence >= 1",
    )
    op.create_check_constraint(
        "ck_reserve_history_source_kind",
        "reserve_history",
        "source_kind IN ('legacy_unbound','manual','reserve_support','adjustment')",
    )

    # Historical rows intentionally remain sequence/hash NULL and source_kind
    # legacy_unbound. We do not fabricate an evidential state, idempotency token,
    # actor chain or provenance that was not captured when those reserve writes occurred.


def downgrade() -> None:
    op.drop_constraint("ck_reserve_history_source_kind", "reserve_history", type_="check")
    op.drop_constraint("ck_reserve_history_sequence_positive", "reserve_history", type_="check")
    op.drop_index("ix_reserve_history_reserve_hash", table_name="reserve_history")
    op.drop_index("ix_reserve_history_org_claim_sequence", table_name="reserve_history")
    op.drop_constraint("uq_reserve_history_claim_idempotency", "reserve_history", type_="unique")
    op.drop_constraint("uq_reserve_history_claim_sequence", "reserve_history", type_="unique")
    op.drop_column("reserve_history", "reserve_hash")
    op.drop_column("reserve_history", "previous_reserve_hash")
    op.drop_column("reserve_history", "source_snapshot")
    op.drop_column("reserve_history", "source_state_hash")
    op.drop_column("reserve_history", "source_reference_id")
    op.drop_column("reserve_history", "source_kind")
    op.drop_column("reserve_history", "request_hash")
    op.drop_column("reserve_history", "idempotency_key")
    op.drop_column("reserve_history", "sequence")
