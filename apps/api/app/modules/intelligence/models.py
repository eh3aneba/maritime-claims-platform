import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class AIRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AISemanticKind(str, enum.Enum):
    FACT = "fact"
    OPINION = "opinion"
    INFERENCE = "inference"


class AIReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class AIRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        Index("ix_ai_runs_org_document_created", "organization_id", "document_id", "created_at"),
        Index("ix_ai_runs_status", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    task: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AIRunStatus] = mapped_column(
        Enum(AIRunStatus, name="ai_run_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=AIRunStatus.PENDING,
        server_default=AIRunStatus.PENDING.value,
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    input_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_char_count: Mapped[int] = mapped_column(nullable=False)

    document_type_candidate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    classification_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    raw_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_response_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentExtraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        UniqueConstraint("ai_run_id", "field_path", name="uq_document_extractions_run_field"),
        Index("ix_document_extractions_org_document", "organization_id", "document_id"),
        Index("ix_document_extractions_review", "organization_id", "human_status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    ai_run_id: Mapped[UUID] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_segment_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_segments.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    field_path: Mapped[str] = mapped_column(String(220), nullable=False)
    semantic_kind: Mapped[AISemanticKind] = mapped_column(
        Enum(AISemanticKind, name="ai_semantic_kind", native_enum=True, values_callable=enum_values),
        nullable=False,
    )
    raw_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    normalized_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    source_locator_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_locator_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_verified: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    validation_warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    human_status: Mapped[AIReviewStatus] = mapped_column(
        Enum(AIReviewStatus, name="ai_review_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=AIReviewStatus.PENDING,
        server_default=AIReviewStatus.PENDING.value,
    )
    approved_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
