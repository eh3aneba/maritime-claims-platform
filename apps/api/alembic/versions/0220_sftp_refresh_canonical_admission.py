"""Allow canonical refresh admission for SFTP Evidence families.

Revision ID: 0220_sftp_refresh_canonical_admission
Revises: 0219_sftp_observation_refresh_execution
"""

from alembic import op

revision = "0220_sftp_refresh_canonical_admission"
down_revision = "0219_sftp_observation_refresh_execution"
branch_labels = None
depends_on = None

AUTH = "external_doc_source_observation_refresh_admission_auths"
EXEC = "external_doc_source_observation_refresh_admission_execs"


def upgrade() -> None:
    op.drop_constraint("ck_ext_doc_obs_refresh_adm_auth_provider", AUTH, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_refresh_adm_auth_provider",
        AUTH,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )
    op.drop_constraint("ck_ext_doc_obs_refresh_adm_exec_provider", EXEC, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_refresh_adm_exec_provider",
        EXEC,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    auth_rows = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {AUTH} WHERE provider_kind = 'sftp'"
    ).scalar_one()
    exec_rows = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {EXEC} WHERE provider_kind = 'sftp'"
    ).scalar_one()
    if auth_rows or exec_rows:
        raise RuntimeError(
            "Cannot downgrade SFTP refresh admission while SFTP admission rows exist"
        )

    op.drop_constraint("ck_ext_doc_obs_refresh_adm_exec_provider", EXEC, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_refresh_adm_exec_provider",
        EXEC,
        "provider_kind IN ('sharepoint','google_drive')",
    )
    op.drop_constraint("ck_ext_doc_obs_refresh_adm_auth_provider", AUTH, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_refresh_adm_auth_provider",
        AUTH,
        "provider_kind IN ('sharepoint','google_drive')",
    )
