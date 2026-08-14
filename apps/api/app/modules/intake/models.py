import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.documents.models import DocumentMalwareScanStatus
from app.modules.processing.models import ProcessingJobStatus


class ClaimIntakeStatus(str, enum.Enum):
    PROCESSING = "processing"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    INFECTED = "infected"
    SCAN_ERROR = "scan_error"


class ClaimIntakeDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_intake_drafts"
    __table_args__ = (
        UniqueConstraint("organization_id", "file_hash", name="uq_claim_intake_org_hash"),
        Index("ix_claim_intake_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    uploaded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True, unique=True
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    malware_scan_status: Mapped[DocumentMalwareScanStatus] = mapped_column(
        Enum(
            DocumentMalwareScanStatus,
            name="document_malware_scan_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    malware_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    threat_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ClaimIntakeStatus] = mapped_column(
        Enum(
            ClaimIntakeStatus,
            name="claim_intake_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ClaimIntakeStatus.PROCESSING,
        server_default=ClaimIntakeStatus.PROCESSING.value,
    )
    extraction_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ocr_languages: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    extraction_warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    classification_candidate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    classification_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    field_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClaimIntakeProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_intake_processing_jobs"
    __table_args__ = (
        UniqueConstraint("intake_draft_id", name="uq_claim_intake_processing_job_draft"),
        Index("ix_claim_intake_jobs_status_available", "status", "available_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    intake_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("claim_intake_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(
            ProcessingJobStatus,
            name="processing_job_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ProcessingJobStatus.PENDING,
        server_default=ProcessingJobStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
