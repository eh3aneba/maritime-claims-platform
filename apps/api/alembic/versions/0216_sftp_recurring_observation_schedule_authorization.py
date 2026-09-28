"""Authorize recurring observation schedules for SFTP Evidence families.

Revision ID: 0216_sftp_recurring_observation_schedule
Revises: 0215_provider_neutral_recurring_lineage
"""

from alembic import op

revision = "0216_sftp_recurring_observation_schedule"
down_revision = "0215_provider_neutral_recurring_lineage"
branch_labels = None
depends_on = None

SCHEDULE = "external_doc_source_recurring_observation_schedules"


def upgrade() -> None:
    op.drop_constraint("ck_ext_doc_obs_sched_provider", SCHEDULE, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_sched_provider",
        SCHEDULE,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    sftp_rows = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {SCHEDULE} WHERE provider_kind = 'sftp'"
    ).scalar_one()
    if sftp_rows:
        raise RuntimeError(
            "Cannot downgrade SFTP recurring schedule authorization while SFTP schedules exist"
        )

    op.drop_constraint("ck_ext_doc_obs_sched_provider", SCHEDULE, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_sched_provider",
        SCHEDULE,
        "provider_kind IN ('sharepoint','google_drive')",
    )
