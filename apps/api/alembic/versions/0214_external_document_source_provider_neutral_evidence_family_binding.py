"""Make external Evidence-family admission lineage provider-neutral.

Revision ID: 0214_provider_neutral_evidence_family_binding
Revises: 0213_sftp_evidence_admission_execution
"""

from alembic import op
import sqlalchemy as sa

revision = "0214_provider_neutral_evidence_family_binding"
down_revision = "0213_sftp_evidence_admission_execution"
branch_labels = None
depends_on = None

BINDING = "external_doc_source_evidence_family_bindings"
SFTP_EXECUTION = "external_doc_source_sftp_evidence_admission_execs"


def upgrade() -> None:
    op.add_column(
        BINDING,
        sa.Column("sftp_admission_execution_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ext_doc_efb_sftp_admission",
        BINDING,
        SFTP_EXECUTION,
        ["sftp_admission_execution_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_ext_doc_efb_sftp_admission",
        BINDING,
        ["sftp_admission_execution_id"],
    )
    op.create_index(
        "ix_ext_doc_efb_sftp_admission",
        BINDING,
        ["sftp_admission_execution_id"],
    )

    op.alter_column(
        BINDING,
        "admission_execution_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    op.drop_constraint(
        "ck_ext_doc_efb_provider",
        BINDING,
        type_="check",
    )
    op.create_check_constraint(
        "ck_ext_doc_efb_provider",
        BINDING,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )
    op.create_check_constraint(
        "ck_ext_doc_efb_admission_lineage",
        BINDING,
        "("
        "(provider_kind IN ('sharepoint','google_drive') "
        "AND admission_execution_id IS NOT NULL "
        "AND sftp_admission_execution_id IS NULL) "
        "OR "
        "(provider_kind = 'sftp' "
        "AND admission_execution_id IS NULL "
        "AND sftp_admission_execution_id IS NOT NULL)"
        ")",
    )


def downgrade() -> None:
    connection = op.get_bind()
    sftp_rows = connection.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {BINDING} "
            "WHERE provider_kind = 'sftp' "
            "OR sftp_admission_execution_id IS NOT NULL"
        )
    ).scalar_one()
    if sftp_rows:
        raise RuntimeError(
            "Cannot downgrade provider-neutral Evidence-family binding while "
            "SFTP family bindings exist"
        )

    op.drop_constraint(
        "ck_ext_doc_efb_admission_lineage",
        BINDING,
        type_="check",
    )
    op.drop_constraint(
        "ck_ext_doc_efb_provider",
        BINDING,
        type_="check",
    )
    op.create_check_constraint(
        "ck_ext_doc_efb_provider",
        BINDING,
        "provider_kind IN ('sharepoint','google_drive')",
    )

    op.alter_column(
        BINDING,
        "admission_execution_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    op.drop_index(
        "ix_ext_doc_efb_sftp_admission",
        table_name=BINDING,
    )
    op.drop_constraint(
        "uq_ext_doc_efb_sftp_admission",
        BINDING,
        type_="unique",
    )
    op.drop_constraint(
        "fk_ext_doc_efb_sftp_admission",
        BINDING,
        type_="foreignkey",
    )
    op.drop_column(BINDING, "sftp_admission_execution_id")
