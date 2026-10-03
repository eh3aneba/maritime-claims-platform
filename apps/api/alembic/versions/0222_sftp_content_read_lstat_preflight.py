"""Permit a truthful bounded SFTP lstat preflight before content read.

Revision ID: 0222_sftp_content_read_lstat_preflight
Revises: 0221_sftp_recurring_baseline_transition
"""

from alembic import op

revision = "0222_sftp_content_read_lstat_preflight"
down_revision = "0221_sftp_recurring_baseline_transition"
branch_labels = None
depends_on = None

PROOF = "external_doc_source_sftp_file_content_proofs"
RECEIPT = "external_doc_source_sftp_file_content_proof_receipts"


def upgrade() -> None:
    op.drop_constraint(
        "ck_ext_doc_sftp_content_proof_no_remote_stat_performed",
        PROOF,
        type_="check",
    )
    op.create_check_constraint(
        "ck_ext_doc_sftp_content_proof_stat_session",
        PROOF,
        "remote_stat_performed = false OR sftp_session_opened = true",
    )

    op.drop_constraint(
        "ck_ext_doc_sftp_content_proof_rcpt_no_remote_stat_performed",
        RECEIPT,
        type_="check",
    )
    op.create_check_constraint(
        "ck_ext_doc_sftp_content_proof_rcpt_stat_session",
        RECEIPT,
        "remote_stat_performed = false OR sftp_session_opened = true",
    )


def downgrade() -> None:
    connection = op.get_bind()
    proof_count = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {PROOF} WHERE remote_stat_performed = true"
    ).scalar_one()
    receipt_count = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM {RECEIPT} WHERE remote_stat_performed = true"
    ).scalar_one()
    if proof_count or receipt_count:
        raise RuntimeError(
            "Cannot downgrade SFTP content-read lstat support while lstat-backed rows exist"
        )

    op.drop_constraint(
        "ck_ext_doc_sftp_content_proof_rcpt_stat_session",
        RECEIPT,
        type_="check",
    )
    op.create_check_constraint(
        "ck_ext_doc_sftp_content_proof_rcpt_no_remote_stat_performed",
        RECEIPT,
        "remote_stat_performed = false",
    )

    op.drop_constraint(
        "ck_ext_doc_sftp_content_proof_stat_session",
        PROOF,
        type_="check",
    )
    op.create_check_constraint(
        "ck_ext_doc_sftp_content_proof_no_remote_stat_performed",
        PROOF,
        "remote_stat_performed = false",
    )
