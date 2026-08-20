"""version production control verification scope

Revision ID: 0036_control_scope
Revises: 0035_control_verification
"""
import sqlalchemy as sa
from alembic import op

revision = "0036_control_scope"
down_revision = "0035_control_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing Sprint 10C rows retain the five-control profile. The server default is
    # then advanced so inserts that do not pass through the ORM still use Sprint 10D.
    op.add_column(
        "production_control_verification_gates",
        sa.Column(
            "verification_profile", sa.String(40),
            server_default="foundational_v1", nullable=False,
        ),
    )
    op.alter_column(
        "production_control_verification_gates", "verification_profile",
        existing_type=sa.String(40), server_default="architecture_v2", nullable=False,
    )


def downgrade() -> None:
    op.drop_column("production_control_verification_gates", "verification_profile")
