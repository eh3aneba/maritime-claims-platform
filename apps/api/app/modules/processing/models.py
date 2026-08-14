import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class ProcessingJobType(str, enum.Enum):
    EXTRACT_TEXT = "extract_text"
    MALWARE_RESCAN = "malware_rescan"
    AI_EXTRACT_CE_REPORT = "ai_extract_ce_report"
    AI_EXTRACT_ENGINE_LOG = "ai_extract_engine_log"
    AI_EXTRACT_RUNNING_HOURS = "ai_extract_running_hours"
    AI_EXTRACT_PMS_HISTORY = "ai_extract_pms_history"
    AI_EXTRACT_WORKSHOP_REPORT = "ai_extract_workshop_report"
    AI_EXTRACT_QUOTATION = "ai_extract_quotation"
    AI_EXTRACT_INVOICE = "ai_extract_invoice"


class ProcessingJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_status_available", "status", "available_at"),
        Index("ix_processing_jobs_org_document", "organization_id", "document_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    job_type: Mapped[ProcessingJobType] = mapped_column(
        Enum(ProcessingJobType, name="processing_job_type", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ProcessingJobType.EXTRACT_TEXT,
        server_default=ProcessingJobType.EXTRACT_TEXT.value,
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(ProcessingJobStatus, name="processing_job_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ProcessingJobStatus.PENDING,
        server_default=ProcessingJobStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DocumentTextExtraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_text_extractions"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_text_extractions_document"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    extraction_method: Mapped[str] = mapped_column(String(80), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    requires_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)


class DocumentTextSegment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_text_segments"
    __table_args__ = (
        UniqueConstraint("extraction_id", "segment_index", name="uq_document_text_segment_index"),
        Index("ix_document_text_segments_document", "document_id", "segment_index"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    extraction_id: Mapped[UUID] = mapped_column(ForeignKey("document_text_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    locator_type: Mapped[str] = mapped_column(String(30), nullable=False)
    locator_value: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
