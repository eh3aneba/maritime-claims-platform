import enum
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class ChronologyMateriality(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConflictStatus(str, enum.Enum):
    OPEN = "open"
    EXPLAINED = "explained"
    RESOLVED = "resolved"
    ACCEPTED_DIFFERENCE = "accepted_difference"
    IRRELEVANT = "irrelevant"


class ChronologyEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chronology_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "source_signature", name="uq_chronology_event_signature"),
        Index("ix_chronology_events_org_claim_active", "organization_id", "claim_id", "is_active"),
        Index("ix_chronology_events_claim_time", "claim_id", "occurred_on", "occurred_time"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)

    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    timezone_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    materiality: Mapped[ChronologyMateriality] = mapped_column(
        Enum(ChronologyMateriality, name="chronology_materiality", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ChronologyMateriality.MEDIUM,
        server_default=ChronologyMateriality.MEDIUM.value,
    )
    source_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(80), nullable=False, default="chronology_rules_v1", server_default="chronology_rules_v1")
    build_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0", server_default="1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class EventEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_evidence"
    __table_args__ = (
        UniqueConstraint("event_id", "extraction_id", name="uq_event_evidence_event_extraction"),
        Index("ix_event_evidence_org_event", "organization_id", "event_id"),
        Index("ix_event_evidence_claim", "claim_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("chronology_events.id", ondelete="CASCADE"), nullable=False, index=True)
    extraction_id: Mapped[UUID] = mapped_column(ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_segment_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_segments.id", ondelete="SET NULL"), nullable=True)
    evidence_role: Mapped[str] = mapped_column(String(30), nullable=False, default="supporting", server_default="supporting")


class EvidenceConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_conflicts"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "conflict_key", name="uq_evidence_conflict_key"),
        Index("ix_evidence_conflicts_org_claim_active", "organization_id", "claim_id", "is_active"),
        Index("ix_evidence_conflicts_status", "organization_id", "status"),
        CheckConstraint("state_version >= 1", name="ck_evidence_conflict_state_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_a_id: Mapped[UUID | None] = mapped_column(ForeignKey("chronology_events.id", ondelete="SET NULL"), nullable=True)
    event_b_id: Mapped[UUID | None] = mapped_column(ForeignKey("chronology_events.id", ondelete="SET NULL"), nullable=True)
    evidence_a_extraction_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True)
    evidence_b_extraction_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True)

    conflict_key: Mapped[str] = mapped_column(String(64), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(50), nullable=False)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value_a: Mapped[object | None] = mapped_column(JSON, nullable=True)
    value_b: Mapped[object | None] = mapped_column(JSON, nullable=True)
    difference_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    materiality: Mapped[ChronologyMateriality] = mapped_column(
        Enum(ChronologyMateriality, name="chronology_materiality", native_enum=True, values_callable=enum_values),
        nullable=False,
    )
    state_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[ConflictStatus] = mapped_column(
        Enum(ConflictStatus, name="evidence_conflict_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ConflictStatus.OPEN,
        server_default=ConflictStatus.OPEN.value,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class EvidenceConflictDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_conflict_decisions"
    __table_args__ = (
        UniqueConstraint("conflict_id", "decision_number", name="uq_evidence_conflict_decision_number"),
        Index(
            "ix_evidence_conflict_decisions_org_claim_conflict",
            "organization_id",
            "claim_id",
            "conflict_id",
            "decision_number",
        ),
        CheckConstraint("state_version >= 1", name="ck_evidence_conflict_decision_state_version"),
        CheckConstraint("decision_number >= 1", name="ck_evidence_conflict_decision_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    conflict_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_conflicts.id", ondelete="CASCADE"), nullable=False, index=True)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ConflictStatus] = mapped_column(
        Enum(ConflictStatus, name="evidence_conflict_status", native_enum=True, values_callable=enum_values),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
