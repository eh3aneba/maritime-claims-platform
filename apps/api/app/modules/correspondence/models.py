import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class CorrespondenceDirection(str, enum.Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    INTERNAL = "internal"


class CorrespondenceKind(str, enum.Enum):
    DOCUMENT_REQUEST = "document_request"
    FOLLOW_UP = "follow_up"
    STATUS_UPDATE = "status_update"
    RESERVATION_OF_RIGHTS = "reservation_of_rights"
    SETTLEMENT = "settlement"
    GENERAL = "general"


class CorrespondenceStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT_EXTERNALLY = "sent_externally"
    RECEIVED_EXTERNAL = "received_external"
    FILED_INTERNAL = "filed_internal"
    CANCELLED = "cancelled"


class CorrespondenceSensitivity(str, enum.Enum):
    STANDARD = "standard"
    CONFIDENTIAL = "confidential"
    PRIVILEGED_CONFIDENTIAL = "privileged_confidential"
    WITHOUT_PREJUDICE = "without_prejudice"


class CorrespondenceChannel(str, enum.Enum):
    EMAIL = "email"
    LETTER = "letter"
    PORTAL = "portal"
    PHONE = "phone"
    MEETING = "meeting"
    OTHER = "other"


class ClaimCorrespondence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_correspondence"
    __table_args__ = (
        Index("ix_claim_correspondence_org_claim_created", "organization_id", "claim_id", "created_at"),
        Index("ix_claim_correspondence_org_claim_status", "organization_id", "claim_id", "status"),
        UniqueConstraint("request_batch_id", name="uq_claim_correspondence_request_batch"),
        CheckConstraint("state_version >= 1", name="ck_claim_correspondence_state_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_request_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sent_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    direction: Mapped[CorrespondenceDirection] = mapped_column(Enum(CorrespondenceDirection, name="correspondence_direction", native_enum=True, values_callable=enum_values), nullable=False)
    kind: Mapped[CorrespondenceKind] = mapped_column(Enum(CorrespondenceKind, name="correspondence_kind", native_enum=True, values_callable=enum_values), nullable=False)
    status: Mapped[CorrespondenceStatus] = mapped_column(Enum(CorrespondenceStatus, name="correspondence_status", native_enum=True, values_callable=enum_values), nullable=False)
    sensitivity: Mapped[CorrespondenceSensitivity] = mapped_column(Enum(CorrespondenceSensitivity, name="correspondence_sensitivity", native_enum=True, values_callable=enum_values), nullable=False)
    channel: Mapped[CorrespondenceChannel | None] = mapped_column(Enum(CorrespondenceChannel, name="correspondence_channel", native_enum=True, values_callable=enum_values), nullable=True)

    sender_label: Mapped[str | None] = mapped_column(String(180), nullable=True)
    recipient_label: Mapped[str | None] = mapped_column(String(180), nullable=True)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(240), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    sent_review_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CorrespondenceReviewDecision(UUIDPrimaryKeyMixin, Base):
    """Append-only human review lineage bound to one exact correspondence state."""

    __tablename__ = "correspondence_review_decisions"
    __table_args__ = (
        UniqueConstraint("correspondence_id", "review_number", name="uq_correspondence_review_number"),
        Index(
            "ix_correspondence_review_claim",
            "organization_id",
            "claim_id",
            "correspondence_id",
            "review_number",
        ),
        CheckConstraint("state_version >= 1", name="ck_correspondence_review_state_version"),
        CheckConstraint("review_number >= 1", name="ck_correspondence_review_number"),
        CheckConstraint("action IN ('approve','reject')", name="ck_correspondence_review_action"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    correspondence_id: Mapped[UUID] = mapped_column(ForeignKey("claim_correspondence.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    correspondence_state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    review_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_review_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
