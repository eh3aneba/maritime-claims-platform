"""Repair legacy SFTP no-stat constraints after lstat preflight rollout.

Revision ID: 0223_sftp_content_read_lstat_constraint_repair
Revises: 0222_sftp_content_read_lstat_preflight
Create Date: 2026-10-06 10:55:00
"""

from alembic import op
from sqlalchemy.engine.reflection import Inspector


revision = "0223_sftp_content_read_lstat_constraint_repair"
down_revision = "0222_sftp_content_read_lstat_preflight"
branch_labels = None
depends_on = None

_PROOF_TABLE_NAME = "external_doc_source_sftp_file_content_proofs"
_PROOF_CONSTRAINT_NAME = "ck_ext_doc_sftp_content_proof_no_stat"
_RECEIPT_TABLE_NAME = "external_doc_source_sftp_file_content_proof_receipts"
_RECEIPT_CONSTRAINT_NAME = "ck_ext_doc_sftp_content_proof_rcpt_no_stat"


def _existing_check_constraints(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def _drop_legacy_no_stat_constraint(table_name: str, constraint_name: str) -> None:
    if constraint_name in _existing_check_constraints(table_name):
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="check",
        )


def _restore_legacy_no_stat_constraint(table_name: str, constraint_name: str) -> None:
    if constraint_name not in _existing_check_constraints(table_name):
        op.create_check_constraint(
            constraint_name,
            table_name,
            "remote_stat_performed = false",
        )


def upgrade() -> None:
    _drop_legacy_no_stat_constraint(_PROOF_TABLE_NAME, _PROOF_CONSTRAINT_NAME)
    _drop_legacy_no_stat_constraint(_RECEIPT_TABLE_NAME, _RECEIPT_CONSTRAINT_NAME)


def downgrade() -> None:
    _restore_legacy_no_stat_constraint(_PROOF_TABLE_NAME, _PROOF_CONSTRAINT_NAME)
    _restore_legacy_no_stat_constraint(_RECEIPT_TABLE_NAME, _RECEIPT_CONSTRAINT_NAME)
