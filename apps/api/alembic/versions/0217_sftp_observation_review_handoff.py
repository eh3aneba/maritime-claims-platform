"""Allow SFTP due-tick observations to enter review handoff.

Revision ID: 0217_sftp_observation_review_handoff
Revises: 0216_sftp_recurring_observation_schedule
"""

from alembic import op

revision = "0217_sftp_observation_review_handoff"
down_revision = "0216_sftp_recurring_observation_schedule"
branch_labels = None
depends_on = None

HANDOFF = "external_doc_source_observation_review_handoffs"


def upgrade() -> None:
    op.drop_constraint("ck_ext_doc_obs_review_provider", HANDOFF, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_review_provider",
        HANDOFF,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    sftp_rows = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {HANDOFF} WHERE provider_kind = 'sftp'"
    ).scalar_one()
    if sftp_rows:
        raise RuntimeError(
            "Cannot downgrade SFTP review-handoff support while SFTP handoffs exist"
        )

    op.drop_constraint("ck_ext_doc_obs_review_provider", HANDOFF, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_review_provider",
        HANDOFF,
        "provider_kind IN ('sharepoint','google_drive')",
    )
