"""Permit a truthful bounded SFTP lstat preflight before content read.

Revision ID: 0222_sftp_content_read_lstat_preflight
Revises: 0221_sftp_recurring_baseline_transition
"""

import sqlalchemy as sa
from alembic import op

revision = "0222_sftp_content_read_lstat_preflight"
down_revision = "0221_sftp_recurring_baseline_transition"
branch_labels = None
depends_on = None

PROOF = "external_doc_source_sftp_file_content_proofs"
RECEIPT = "external_doc_source_sftp_file_content_proof_receipts"


def _check_constraint_exists(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        constraint.get("name") == constraint_name
        for constraint in inspector.get_check_constraints(table_name)
    )


def upgrade() -> None:
    proof_legacy_constraint = (
        "ck_ext_doc_sftp_content_proof_no_remote_stat_performed"
    )
    if _check_constraint_exists(PROOF, proof_legacy_constraint):
        op.drop_constraint(
            proof_legacy_constraint,
            PROOF,
            type_="check",
        )
    op.create_check_constraint(
        "ck_ext_doc_sftp_content_proof_stat_session",
        PROOF,
        "remote_stat_performed = false OR sftp_session_opened = true",
    )

    receipt_legacy_constraint = (
        "ck_ext_doc_sftp_content_proof_rcpt_no_remote_stat_performed"
    )
    if _check_constraint_exists(RECEIPT, receipt_legacy_constraint):
        op.drop_constraint(
            receipt_legacy_constraint,
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
