"""Bind correspondence human reviews to dynamic document-request context.

Revision ID: 0077_correspondence_request_context
Revises: 0076_correspondence_review_integrity
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0077_correspondence_request_context"
down_revision = "0076_correspondence_review_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable by design. Existing request-linked reviews cannot be proven to have been reviewed
    # against the exact current requirement/request state, so they remain legacy-unbound until a
    # deliberate human re-review. Free-form correspondence has no request-context fingerprint.
    op.add_column(
        "correspondence_review_decisions",
        sa.Column("request_context_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_correspondence_review_request_context",
        "correspondence_review_decisions",
        ["request_context_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_correspondence_review_request_context",
        table_name="correspondence_review_decisions",
    )
    op.drop_column("correspondence_review_decisions", "request_context_fingerprint")
