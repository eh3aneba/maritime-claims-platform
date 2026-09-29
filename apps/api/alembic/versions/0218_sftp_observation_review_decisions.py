"""Allow SFTP handoffs to receive human review decisions.

Revision ID: 0218_sftp_observation_review_decisions
Revises: 0217_sftp_observation_review_handoff
"""

from alembic import op

revision = "0218_sftp_observation_review_decisions"
down_revision = "0217_sftp_observation_review_handoff"
branch_labels = None
depends_on = None

DECISIONS = "external_doc_source_observation_review_decisions"


def upgrade() -> None:
    op.drop_constraint("ck_ext_doc_obs_review_dec_provider", DECISIONS, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_review_dec_provider",
        DECISIONS,
        "provider_kind IN ('sharepoint','google_drive','sftp')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    sftp_rows = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {DECISIONS} WHERE provider_kind = 'sftp'"
    ).scalar_one()
    if sftp_rows:
        raise RuntimeError(
            "Cannot downgrade SFTP review-decision support while SFTP decisions exist"
        )

    op.drop_constraint("ck_ext_doc_obs_review_dec_provider", DECISIONS, type_="check")
    op.create_check_constraint(
        "ck_ext_doc_obs_review_dec_provider",
        DECISIONS,
        "provider_kind IN ('sharepoint','google_drive')",
    )
