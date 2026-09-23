"""Allow governed SFTP external document source profiles.

Revision ID: 0194_external_doc_source_sftp_profile
Revises: 0193_external_doc_obs_refresh_adm_exec
"""

from alembic import op

revision = "0194_external_doc_source_sftp_profile"
down_revision = "0193_external_doc_obs_refresh_adm_exec"
branch_labels = None
depends_on = None

PROFILE = "external_document_source_profiles"
CONSTRAINT = "ck_ext_doc_source_provider"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, PROFILE, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        PROFILE,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, PROFILE, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        PROFILE,
        "provider_kind IN ('sharepoint','google_drive')",
    )
