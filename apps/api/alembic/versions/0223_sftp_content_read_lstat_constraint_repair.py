"""Repair the legacy SFTP no-stat constraint after lstat preflight rollout.

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

_TABLE_NAME = "external_doc_source_sftp_file_content_proofs"
_CONSTRAINT_NAME = "ck_ext_doc_sftp_content_proof_no_stat"


def _existing_check_constraints() -> set[str]:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(_TABLE_NAME)
        if constraint.get("name")
    }


def upgrade() -> None:
    if _CONSTRAINT_NAME in _existing_check_constraints():
        op.drop_constraint(
            _CONSTRAINT_NAME,
            _TABLE_NAME,
            type_="check",
        )


def downgrade() -> None:
    if _CONSTRAINT_NAME not in _existing_check_constraints():
        op.create_check_constraint(
            _CONSTRAINT_NAME,
            _TABLE_NAME,
            "remote_stat_performed = false",
        )
