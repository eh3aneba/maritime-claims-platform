"""chronology and evidence conflicts

Revision ID: 0007_chronology_conflicts
Revises: 0006_engine_log_intelligence
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_chronology_conflicts"
down_revision: Union[str, None] = "0006_engine_log_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    materiality = postgresql.ENUM("low", "medium", "high", "critical", name="chronology_materiality", create_type=False)
    conflict_status = postgresql.ENUM("open", "explained", "resolved", "accepted_difference", "irrelevant", name="evidence_conflict_status", create_type=False)
    materiality.create(op.get_bind(), checkfirst=True)
    conflict_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "chronology_events",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("occurred_time", sa.Time(timezone=False), nullable=False),
        sa.Column("timezone_label", sa.String(length=50), nullable=True),
        sa.Column("materiality", materiality, server_default="medium", nullable=False),
        sa.Column("source_signature", sa.String(length=64), nullable=False),
        sa.Column("generated_by", sa.String(length=80), server_default="chronology_rules_v1", nullable=False),
        sa.Column("build_version", sa.String(length=30), server_default="1.0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "source_signature", name="uq_chronology_event_signature"),
    )
    op.create_index("ix_chronology_events_organization_id", "chronology_events", ["organization_id"])
    op.create_index("ix_chronology_events_claim_id", "chronology_events", ["claim_id"])
    op.create_index("ix_chronology_events_org_claim_active", "chronology_events", ["organization_id", "claim_id", "is_active"])
    op.create_index("ix_chronology_events_claim_time", "chronology_events", ["claim_id", "occurred_on", "occurred_time"])

    op.create_table(
        "event_evidence",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_role", sa.String(length=30), server_default="supporting", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["chronology_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_segment_id"], ["document_text_segments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "extraction_id", name="uq_event_evidence_event_extraction"),
    )
    op.create_index("ix_event_evidence_organization_id", "event_evidence", ["organization_id"])
    op.create_index("ix_event_evidence_claim_id", "event_evidence", ["claim_id"])
    op.create_index("ix_event_evidence_event_id", "event_evidence", ["event_id"])
    op.create_index("ix_event_evidence_extraction_id", "event_evidence", ["extraction_id"])
    op.create_index("ix_event_evidence_document_id", "event_evidence", ["document_id"])
    op.create_index("ix_event_evidence_org_event", "event_evidence", ["organization_id", "event_id"])
    op.create_index("ix_event_evidence_claim", "event_evidence", ["claim_id"])

    op.create_table(
        "evidence_conflicts",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_a_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_b_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_a_extraction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_b_extraction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conflict_key", sa.String(length=64), nullable=False),
        sa.Column("conflict_type", sa.String(length=50), nullable=False),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("value_a", sa.JSON(), nullable=True),
        sa.Column("value_b", sa.JSON(), nullable=True),
        sa.Column("difference_minutes", sa.Numeric(10, 2), nullable=True),
        sa.Column("materiality", materiality, nullable=False),
        sa.Column("status", conflict_status, server_default="open", nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_a_id"], ["chronology_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_b_id"], ["chronology_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evidence_a_extraction_id"], ["document_extractions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evidence_b_extraction_id"], ["document_extractions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "conflict_key", name="uq_evidence_conflict_key"),
    )
    op.create_index("ix_evidence_conflicts_organization_id", "evidence_conflicts", ["organization_id"])
    op.create_index("ix_evidence_conflicts_claim_id", "evidence_conflicts", ["claim_id"])
    op.create_index("ix_evidence_conflicts_org_claim_active", "evidence_conflicts", ["organization_id", "claim_id", "is_active"])
    op.create_index("ix_evidence_conflicts_status", "evidence_conflicts", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_table("evidence_conflicts")
    op.drop_table("event_evidence")
    op.drop_table("chronology_events")
    op.execute("DROP TYPE evidence_conflict_status")
    op.execute("DROP TYPE chronology_materiality")
