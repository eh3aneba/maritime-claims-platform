"""Requirement evidence state and append-only human disposition history.

Revision ID: 0068_claim_document_requirement_lineage
Revises: 0067_chronology_conflict_decisions
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0068_claim_document_requirement_lineage"
down_revision = "0067_chronology_conflict_decisions"
branch_labels = None
depends_on = None


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _legacy_state_fingerprint(row: dict[str, Any]) -> str:
    """Seed an identity token without pretending legacy mutable state is full lineage.

    Runtime Phase 13.4B synchronization recalculates the fingerprint from current
    document/fact evidence and advances state_version when that evidence differs.
    """

    return _canonical_hash(
        {
            "migration": revision,
            "requirement_id": str(row["id"]),
            "rule_id": row["rule_id"],
            "rule_version": row["rule_version"],
            "document_type": row["document_type"],
        }
    )


def _decision_hash(
    *,
    requirement_id: Any,
    state_fingerprint: str,
    note: str,
    claim_fact_id: Any,
    claim_fact_version: int | None,
    source_document_id: Any,
    source_document_version: int | None,
    decided_by_id: Any,
) -> str:
    return _canonical_hash(
        {
            "requirement_id": str(requirement_id),
            "state_fingerprint": state_fingerprint,
            "state_version": 1,
            "decision_number": 1,
            "action": "accept_equivalent",
            "note": note,
            "claim_fact_id": str(claim_fact_id) if claim_fact_id else None,
            "claim_fact_version": claim_fact_version,
            "source_document_id": str(source_document_id) if source_document_id else None,
            "source_document_version": source_document_version,
            "decided_by_id": str(decided_by_id) if decided_by_id else None,
            "previous_decision_hash": None,
        }
    )


def upgrade() -> None:
    op.create_table(
        "claim_document_requirement_states",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["claim_document_requirements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", name="uq_claim_document_requirement_state_requirement"),
        sa.CheckConstraint("state_version >= 1", name="ck_claim_document_requirement_state_version"),
    )
    op.create_index(
        "ix_claim_document_requirement_states_org_claim_requirement",
        "claim_document_requirement_states",
        ["organization_id", "claim_id", "requirement_id"],
    )
    op.create_index(
        "ix_claim_document_requirement_states_organization_id",
        "claim_document_requirement_states",
        ["organization_id"],
    )
    op.create_index(
        "ix_claim_document_requirement_states_claim_id",
        "claim_document_requirement_states",
        ["claim_id"],
    )
    op.create_index(
        "ix_claim_document_requirement_states_requirement_id",
        "claim_document_requirement_states",
        ["requirement_id"],
    )

    op.create_table(
        "claim_document_requirement_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("claim_fact_id", sa.Uuid(), nullable=True),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("claim_fact_version", sa.Integer(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_version", sa.Integer(), nullable=True),
        sa.Column("previous_decision_hash", sa.String(length=64), nullable=True),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["claim_document_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["claim_fact_id"], ["claim_facts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "decision_number", name="uq_claim_document_requirement_decision_number"),
        sa.CheckConstraint("state_version >= 1", name="ck_claim_document_requirement_decision_state_version"),
        sa.CheckConstraint("decision_number >= 1", name="ck_claim_document_requirement_decision_number"),
    )
    op.create_index(
        "ix_claim_document_requirement_decisions_org_claim_requirement",
        "claim_document_requirement_decisions",
        ["organization_id", "claim_id", "requirement_id", "decision_number"],
    )
    op.create_index(
        "ix_claim_document_requirement_decisions_organization_id",
        "claim_document_requirement_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_claim_document_requirement_decisions_claim_id",
        "claim_document_requirement_decisions",
        ["claim_id"],
    )
    op.create_index(
        "ix_claim_document_requirement_decisions_requirement_id",
        "claim_document_requirement_decisions",
        ["requirement_id"],
    )
    op.create_index(
        "ix_claim_document_requirement_decisions_claim_fact_id",
        "claim_document_requirement_decisions",
        ["claim_fact_id"],
    )

    bind = op.get_bind()
    requirements = list(
        bind.execute(
            sa.text(
                "SELECT id, organization_id, claim_id, rule_id, rule_version, document_type, "
                "status, satisfaction_basis, satisfaction_note, equivalent_claim_fact_id, "
                "satisfied_by_id, satisfied_at, created_at, updated_at "
                "FROM claim_document_requirements"
            )
        ).mappings()
    )
    state_table = sa.table(
        "claim_document_requirement_states",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("claim_id", sa.Uuid()),
        sa.column("requirement_id", sa.Uuid()),
        sa.column("state_fingerprint", sa.String()),
        sa.column("state_version", sa.Integer()),
    )
    decision_table = sa.table(
        "claim_document_requirement_decisions",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("claim_id", sa.Uuid()),
        sa.column("requirement_id", sa.Uuid()),
        sa.column("decided_by_id", sa.Uuid()),
        sa.column("claim_fact_id", sa.Uuid()),
        sa.column("state_fingerprint", sa.String()),
        sa.column("state_version", sa.Integer()),
        sa.column("decision_number", sa.Integer()),
        sa.column("action", sa.String()),
        sa.column("note", sa.Text()),
        sa.column("claim_fact_version", sa.Integer()),
        sa.column("source_document_id", sa.Uuid()),
        sa.column("source_document_version", sa.Integer()),
        sa.column("previous_decision_hash", sa.String()),
        sa.column("decision_hash", sa.String()),
        sa.column("decided_at", sa.DateTime(timezone=True)),
    )

    state_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    for proxy in requirements:
        row = dict(proxy)
        fingerprint = _legacy_state_fingerprint(row)
        state_rows.append(
            {
                "id": uuid4(),
                "organization_id": row["organization_id"],
                "claim_id": row["claim_id"],
                "requirement_id": row["id"],
                "state_fingerprint": fingerprint,
                "state_version": 1,
            }
        )
        basis = row["satisfaction_basis"]
        status = row["status"].value if hasattr(row["status"], "value") else str(row["status"])
        if basis != "equivalent_evidence" or status != "accepted" or not row["equivalent_claim_fact_id"]:
            continue

        fact = bind.execute(
            sa.text(
                "SELECT id, version, source_document_id FROM claim_facts "
                "WHERE id = :fact_id AND organization_id = :org_id AND claim_id = :claim_id"
            ),
            {
                "fact_id": row["equivalent_claim_fact_id"],
                "org_id": row["organization_id"],
                "claim_id": row["claim_id"],
            },
        ).mappings().first()
        claim_fact_version = int(fact["version"]) if fact is not None else None
        source_document_id = fact["source_document_id"] if fact is not None else None
        source_document_version = None
        if source_document_id is not None:
            source_document_version = bind.execute(
                sa.text("SELECT version_number FROM documents WHERE id = :document_id"),
                {"document_id": source_document_id},
            ).scalar_one_or_none()
        note = (row["satisfaction_note"] or "Migrated legacy equivalent-evidence acceptance.").strip()
        decided_at = row["satisfied_at"] or row["updated_at"] or row["created_at"] or datetime.now(UTC)
        decision_rows.append(
            {
                "id": uuid4(),
                "organization_id": row["organization_id"],
                "claim_id": row["claim_id"],
                "requirement_id": row["id"],
                "decided_by_id": row["satisfied_by_id"],
                "claim_fact_id": row["equivalent_claim_fact_id"] if fact is not None else None,
                "state_fingerprint": fingerprint,
                "state_version": 1,
                "decision_number": 1,
                "action": "accept_equivalent",
                "note": note,
                "claim_fact_version": claim_fact_version,
                "source_document_id": source_document_id,
                "source_document_version": source_document_version,
                "previous_decision_hash": None,
                "decision_hash": _decision_hash(
                    requirement_id=row["id"],
                    state_fingerprint=fingerprint,
                    note=note,
                    claim_fact_id=row["equivalent_claim_fact_id"] if fact is not None else None,
                    claim_fact_version=claim_fact_version,
                    source_document_id=source_document_id,
                    source_document_version=source_document_version,
                    decided_by_id=row["satisfied_by_id"],
                ),
                "decided_at": decided_at,
            }
        )

    if state_rows:
        op.bulk_insert(state_table, state_rows)
    if decision_rows:
        op.bulk_insert(decision_table, decision_rows)


def downgrade() -> None:
    op.drop_index("ix_claim_document_requirement_decisions_claim_fact_id", table_name="claim_document_requirement_decisions")
    op.drop_index("ix_claim_document_requirement_decisions_requirement_id", table_name="claim_document_requirement_decisions")
    op.drop_index("ix_claim_document_requirement_decisions_claim_id", table_name="claim_document_requirement_decisions")
    op.drop_index("ix_claim_document_requirement_decisions_organization_id", table_name="claim_document_requirement_decisions")
    op.drop_index("ix_claim_document_requirement_decisions_org_claim_requirement", table_name="claim_document_requirement_decisions")
    op.drop_table("claim_document_requirement_decisions")

    op.drop_index("ix_claim_document_requirement_states_requirement_id", table_name="claim_document_requirement_states")
    op.drop_index("ix_claim_document_requirement_states_claim_id", table_name="claim_document_requirement_states")
    op.drop_index("ix_claim_document_requirement_states_organization_id", table_name="claim_document_requirement_states")
    op.drop_index("ix_claim_document_requirement_states_org_claim_requirement", table_name="claim_document_requirement_states")
    op.drop_table("claim_document_requirement_states")
