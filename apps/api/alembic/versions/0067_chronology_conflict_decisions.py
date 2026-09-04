"""Chronology conflict state and append-only decision history

Revision ID: 0067_chronology_conflict_decisions
Revises: 0066_claim_fact_revision_history
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0067_chronology_conflict_decisions"
down_revision = "0066_claim_fact_revision_history"
branch_labels = None
depends_on = None


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _decimal_state(value: Any) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def _state_fingerprint(row: dict[str, Any]) -> str:
    materiality = row["materiality"]
    if hasattr(materiality, "value"):
        materiality = materiality.value
    return _canonical_hash(
        {
            "type": row["conflict_type"],
            "topic": row["topic"],
            "value_a": row["value_a"],
            "value_b": row["value_b"],
            "difference_minutes": _decimal_state(row["difference_minutes"]),
            "materiality": str(materiality),
            "event_a_id": str(row["event_a_id"]) if row["event_a_id"] else None,
            "event_b_id": str(row["event_b_id"]) if row["event_b_id"] else None,
            "evidence_a_extraction_id": str(row["evidence_a_extraction_id"]) if row["evidence_a_extraction_id"] else None,
            "evidence_b_extraction_id": str(row["evidence_b_extraction_id"]) if row["evidence_b_extraction_id"] else None,
        }
    )


def _decision_hash(*, conflict_id: Any, state_fingerprint: str, status: str, note: str, reviewer_id: Any) -> str:
    return _canonical_hash(
        {
            "conflict_id": str(conflict_id),
            "state_fingerprint": state_fingerprint,
            "state_version": 1,
            "decision_number": 1,
            "status": status,
            "note": note,
            "reviewer_id": str(reviewer_id) if reviewer_id else None,
            "previous_decision_hash": None,
        }
    )


def upgrade() -> None:
    op.add_column("evidence_conflicts", sa.Column("state_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("evidence_conflicts", sa.Column("state_version", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.create_check_constraint("ck_evidence_conflict_state_version", "evidence_conflicts", "state_version >= 1")

    conflict_status = postgresql.ENUM(
        "open",
        "explained",
        "resolved",
        "accepted_difference",
        "irrelevant",
        name="evidence_conflict_status",
        create_type=False,
    )
    op.create_table(
        "evidence_conflict_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("status", conflict_status, nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_decision_hash", sa.String(length=64), nullable=True),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conflict_id"], ["evidence_conflicts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conflict_id", "decision_number", name="uq_evidence_conflict_decision_number"),
        sa.CheckConstraint("state_version >= 1", name="ck_evidence_conflict_decision_state_version"),
        sa.CheckConstraint("decision_number >= 1", name="ck_evidence_conflict_decision_number"),
    )
    op.create_index(
        "ix_evidence_conflict_decisions_org_claim_conflict",
        "evidence_conflict_decisions",
        ["organization_id", "claim_id", "conflict_id", "decision_number"],
    )
    op.create_index("ix_evidence_conflict_decisions_organization_id", "evidence_conflict_decisions", ["organization_id"])
    op.create_index("ix_evidence_conflict_decisions_claim_id", "evidence_conflict_decisions", ["claim_id"])
    op.create_index("ix_evidence_conflict_decisions_conflict_id", "evidence_conflict_decisions", ["conflict_id"])

    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT id, organization_id, claim_id, conflict_type, topic, value_a, value_b, "
                "difference_minutes, materiality, event_a_id, event_b_id, evidence_a_extraction_id, "
                "evidence_b_extraction_id, status, resolution_note, resolved_by_id, resolved_at, "
                "created_at, updated_at FROM evidence_conflicts"
            )
        ).mappings()
    )
    decision_table = sa.table(
        "evidence_conflict_decisions",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("claim_id", sa.Uuid()),
        sa.column("conflict_id", sa.Uuid()),
        sa.column("state_fingerprint", sa.String()),
        sa.column("state_version", sa.Integer()),
        sa.column("decision_number", sa.Integer()),
        sa.column("status", conflict_status),
        sa.column("note", sa.Text()),
        sa.column("decided_by_id", sa.Uuid()),
        sa.column("decided_at", sa.DateTime(timezone=True)),
        sa.column("previous_decision_hash", sa.String()),
        sa.column("decision_hash", sa.String()),
    )
    legacy_decisions: list[dict[str, Any]] = []
    for row_proxy in rows:
        row = dict(row_proxy)
        fingerprint = _state_fingerprint(row)
        bind.execute(
            sa.text("UPDATE evidence_conflicts SET state_fingerprint = :fingerprint, state_version = 1 WHERE id = :id"),
            {"fingerprint": fingerprint, "id": row["id"]},
        )
        status = row["status"].value if hasattr(row["status"], "value") else str(row["status"])
        if status == "open":
            continue
        note = (row["resolution_note"] or "Migrated legacy conflict disposition.").strip()
        decided_at = row["resolved_at"] or row["updated_at"] or row["created_at"] or datetime.now(UTC)
        legacy_decisions.append(
            {
                "id": uuid4(),
                "organization_id": row["organization_id"],
                "claim_id": row["claim_id"],
                "conflict_id": row["id"],
                "state_fingerprint": fingerprint,
                "state_version": 1,
                "decision_number": 1,
                "status": status,
                "note": note,
                "decided_by_id": row["resolved_by_id"],
                "decided_at": decided_at,
                "previous_decision_hash": None,
                "decision_hash": _decision_hash(
                    conflict_id=row["id"],
                    state_fingerprint=fingerprint,
                    status=status,
                    note=note,
                    reviewer_id=row["resolved_by_id"],
                ),
            }
        )
    if legacy_decisions:
        op.bulk_insert(decision_table, legacy_decisions)


def downgrade() -> None:
    op.drop_index("ix_evidence_conflict_decisions_conflict_id", table_name="evidence_conflict_decisions")
    op.drop_index("ix_evidence_conflict_decisions_claim_id", table_name="evidence_conflict_decisions")
    op.drop_index("ix_evidence_conflict_decisions_organization_id", table_name="evidence_conflict_decisions")
    op.drop_index("ix_evidence_conflict_decisions_org_claim_conflict", table_name="evidence_conflict_decisions")
    op.drop_table("evidence_conflict_decisions")
    op.drop_constraint("ck_evidence_conflict_state_version", "evidence_conflicts", type_="check")
    op.drop_column("evidence_conflicts", "state_version")
    op.drop_column("evidence_conflicts", "state_fingerprint")
