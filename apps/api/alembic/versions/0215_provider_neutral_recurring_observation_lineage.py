"""Make recurring due-tick provider lineage provider-neutral.

Revision ID: 0215_provider_neutral_recurring_lineage
Revises: 0214_provider_neutral_evidence_family_binding
"""

from alembic import op
import sqlalchemy as sa

revision = "0215_provider_neutral_recurring_lineage"
down_revision = "0214_provider_neutral_evidence_family_binding"
branch_labels = None
depends_on = None

DUE_OBS = "external_doc_source_due_tick_observation_execs"
DUE_DISP = "external_doc_source_due_tick_dispatches"
SFTP_OBS = "external_doc_source_sftp_generation3_change_detections"
SFTP_CP = "external_doc_source_sftp_generation3_checkpoint_advancements"


def upgrade() -> None:
    op.add_column(
        DUE_OBS,
        sa.Column("sftp_provider_lineage_observation_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        DUE_OBS,
        sa.Column("sftp_provider_lineage_checkpoint_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ext_doc_due_obs_sftp_observation",
        DUE_OBS,
        SFTP_OBS,
        ["sftp_provider_lineage_observation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_ext_doc_due_obs_sftp_checkpoint",
        DUE_OBS,
        SFTP_CP,
        ["sftp_provider_lineage_checkpoint_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_ext_doc_due_obs_sftp_observation",
        DUE_OBS,
        ["sftp_provider_lineage_observation_id"],
    )
    op.create_index(
        "ix_ext_doc_due_obs_sftp_checkpoint",
        DUE_OBS,
        ["sftp_provider_lineage_checkpoint_id"],
    )

    op.alter_column(
        DUE_OBS,
        "provider_lineage_observation_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.alter_column(
        DUE_OBS,
        "provider_lineage_checkpoint_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    op.drop_constraint("ck_ext_doc_due_obs_provider", DUE_OBS, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_due_obs_provider",
        DUE_OBS,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )
    op.create_check_constraint(
        "ck_ext_doc_due_obs_lineage_selector",
        DUE_OBS,
        "("
        "(provider_kind IN ('sharepoint','google_drive') "
        "AND provider_lineage_observation_id IS NOT NULL "
        "AND provider_lineage_checkpoint_id IS NOT NULL "
        "AND sftp_provider_lineage_observation_id IS NULL "
        "AND sftp_provider_lineage_checkpoint_id IS NULL) "
        "OR "
        "(provider_kind = 'sftp' "
        "AND provider_lineage_observation_id IS NULL "
        "AND provider_lineage_checkpoint_id IS NULL "
        "AND sftp_provider_lineage_observation_id IS NOT NULL "
        "AND sftp_provider_lineage_checkpoint_id IS NOT NULL)"
        ")",
    )

    op.drop_constraint("ck_ext_doc_due_disp_provider", DUE_DISP, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_due_disp_provider",
        DUE_DISP,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    sftp_due_rows = connection.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {DUE_OBS} "
            "WHERE provider_kind = 'sftp' "
            "OR sftp_provider_lineage_observation_id IS NOT NULL "
            "OR sftp_provider_lineage_checkpoint_id IS NOT NULL"
        )
    ).scalar_one()
    sftp_dispatch_rows = connection.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {DUE_DISP} WHERE provider_kind = 'sftp'"
        )
    ).scalar_one()
    if sftp_due_rows or sftp_dispatch_rows:
        raise RuntimeError(
            "Cannot downgrade provider-neutral recurring lineage while SFTP due-tick rows exist"
        )

    op.drop_constraint("ck_ext_doc_due_obs_lineage_selector", DUE_OBS, type_="check")
    op.drop_constraint("ck_ext_doc_due_obs_provider", DUE_OBS, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_due_obs_provider",
        DUE_OBS,
        "provider_kind IN ('sharepoint','google_drive')",
    )
    op.alter_column(
        DUE_OBS,
        "provider_lineage_observation_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.alter_column(
        DUE_OBS,
        "provider_lineage_checkpoint_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_index("ix_ext_doc_due_obs_sftp_checkpoint", table_name=DUE_OBS)
    op.drop_index("ix_ext_doc_due_obs_sftp_observation", table_name=DUE_OBS)
    op.drop_constraint(
        "fk_ext_doc_due_obs_sftp_checkpoint",
        DUE_OBS,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_ext_doc_due_obs_sftp_observation",
        DUE_OBS,
        type_="foreignkey",
    )
    op.drop_column(DUE_OBS, "sftp_provider_lineage_checkpoint_id")
    op.drop_column(DUE_OBS, "sftp_provider_lineage_observation_id")

    op.drop_constraint("ck_ext_doc_due_disp_provider", DUE_DISP, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_due_disp_provider",
        DUE_DISP,
        "provider_kind IN ('sharepoint','google_drive')",
    )
