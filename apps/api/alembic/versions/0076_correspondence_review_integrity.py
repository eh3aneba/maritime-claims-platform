"""Correspondence state identity and append-only human review lineage.

Revision ID: 0076_correspondence_review_integrity
Revises: 0075_assessment_source_integrity
"""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0076_correspondence_review_integrity"
down_revision = "0075_assessment_source_integrity"
branch_labels = None
depends_on = None


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _state_fingerprint(row) -> str:
    requirement_ids = sorted(str(value) for value in (row["requirement_ids"] or []))
    return _canonical_hash(
        {
            "direction": str(row["direction"]),
            "kind": str(row["kind"]),
            "sensitivity": str(row["sensitivity"]),
            "sender_label": row["sender_label"] or "",
            "recipient_label": row["recipient_label"] or "",
            "subject": (row["subject"] or "").strip(),
            "body": (row["body"] or "").strip(),
            "request_batch_id": str(row["request_batch_id"]) if row["request_batch_id"] else None,
            "requirement_ids": requirement_ids,
        }
    )


def _review_hash(*, row, fingerprint: str, action: str, review_number: int, previous_hash: str | None) -> str:
    return _canonical_hash(
        {
            "organization_id": str(row["organization_id"]),
            "claim_id": str(row["claim_id"]),
            "correspondence_id": str(row["id"]),
            "correspondence_state_fingerprint": fingerprint,
            "state_version": 1,
            "review_number": review_number,
            "action": action,
            "note": (row["review_note"] or "").strip(),
            "content_hash": row["content_hash"] if action == "approve" else None,
            "reviewed_by_id": str(row["reviewed_by_id"]) if row["reviewed_by_id"] else None,
            "previous_review_hash": previous_hash,
        }
    )


def upgrade() -> None:
    op.add_column("claim_correspondence", sa.Column("state_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("claim_correspondence", sa.Column("state_version", sa.Integer(), nullable=True))
    op.add_column("claim_correspondence", sa.Column("sent_review_hash", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_claim_correspondence_state_fingerprint",
        "claim_correspondence",
        ["state_fingerprint"],
    )

    op.create_table(
        "correspondence_review_decisions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("correspondence_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("correspondence_state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("review_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("previous_review_hash", sa.String(length=64), nullable=True),
        sa.Column("review_hash", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["correspondence_id"], ["claim_correspondence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("correspondence_id", "review_number", name="uq_correspondence_review_number"),
        sa.CheckConstraint("state_version >= 1", name="ck_correspondence_review_state_version"),
        sa.CheckConstraint("review_number >= 1", name="ck_correspondence_review_number"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_correspondence_review_action"),
    )
    op.create_index(
        "ix_correspondence_review_claim",
        "correspondence_review_decisions",
        ["organization_id", "claim_id", "correspondence_id", "review_number"],
    )
    op.create_index(
        "ix_correspondence_review_decisions_organization_id",
        "correspondence_review_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_correspondence_review_decisions_claim_id",
        "correspondence_review_decisions",
        ["claim_id"],
    )
    op.create_index(
        "ix_correspondence_review_decisions_correspondence_id",
        "correspondence_review_decisions",
        ["correspondence_id"],
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, organization_id, claim_id, request_batch_id,
                   direction::text AS direction, kind::text AS kind,
                   sensitivity::text AS sensitivity, sender_label, recipient_label,
                   subject, body, requirement_ids, status::text AS status,
                   review_note, reviewed_by_id, reviewed_at, content_hash
            FROM claim_correspondence
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings().all()

    for row in rows:
        fingerprint = _state_fingerprint(row)
        bind.execute(
            sa.text(
                "UPDATE claim_correspondence "
                "SET state_fingerprint = :fingerprint, state_version = 1 WHERE id = :id"
            ),
            {"fingerprint": fingerprint, "id": row["id"]},
        )

        status = str(row["status"])
        has_review = bool(row["reviewed_at"] and row["reviewed_by_id"] and row["review_note"])
        if not has_review or status not in {"approved", "rejected", "sent_externally"}:
            continue
        action = "reject" if status == "rejected" else "approve"
        review_hash = _review_hash(
            row=row,
            fingerprint=fingerprint,
            action=action,
            review_number=1,
            previous_hash=None,
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO correspondence_review_decisions (
                    id, organization_id, claim_id, correspondence_id, reviewed_by_id,
                    correspondence_state_fingerprint, state_version, review_number,
                    action, note, content_hash, previous_review_hash, review_hash, reviewed_at
                ) VALUES (
                    :id, :organization_id, :claim_id, :correspondence_id, :reviewed_by_id,
                    :fingerprint, 1, 1, :action, :note, :content_hash, NULL, :review_hash, :reviewed_at
                )
                """
            ),
            {
                "id": uuid4(),
                "organization_id": row["organization_id"],
                "claim_id": row["claim_id"],
                "correspondence_id": row["id"],
                "reviewed_by_id": row["reviewed_by_id"],
                "fingerprint": fingerprint,
                "action": action,
                "note": row["review_note"].strip(),
                "content_hash": row["content_hash"] if action == "approve" else None,
                "review_hash": review_hash,
                "reviewed_at": row["reviewed_at"],
            },
        )
        if status == "sent_externally" and action == "approve":
            bind.execute(
                sa.text("UPDATE claim_correspondence SET sent_review_hash = :review_hash WHERE id = :id"),
                {"review_hash": review_hash, "id": row["id"]},
            )

    op.alter_column(
        "claim_correspondence",
        "state_fingerprint",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "claim_correspondence",
        "state_version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )
    op.create_check_constraint(
        "ck_claim_correspondence_state_version",
        "claim_correspondence",
        "state_version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_claim_correspondence_state_version", "claim_correspondence", type_="check")
    op.drop_index("ix_correspondence_review_decisions_correspondence_id", table_name="correspondence_review_decisions")
    op.drop_index("ix_correspondence_review_decisions_claim_id", table_name="correspondence_review_decisions")
    op.drop_index("ix_correspondence_review_decisions_organization_id", table_name="correspondence_review_decisions")
    op.drop_index("ix_correspondence_review_claim", table_name="correspondence_review_decisions")
    op.drop_table("correspondence_review_decisions")
    op.drop_index("ix_claim_correspondence_state_fingerprint", table_name="claim_correspondence")
    op.drop_column("claim_correspondence", "sent_review_hash")
    op.drop_column("claim_correspondence", "state_version")
    op.drop_column("claim_correspondence", "state_fingerprint")
