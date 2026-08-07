import enum
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class TaskType(str, enum.Enum):
    DOCUMENT_REQUEST = "document_request"
    REVIEW = "review"
    FOLLOW_UP = "follow_up"


class TaskStatus(str, enum.Enum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskSource(str, enum.Enum):
    HUMAN = "human"
    RULE = "rule"
    AI_SUGGESTION = "ai_suggestion"


class ClaimTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_tasks"
    __table_args__ = (
        Index("ix_claim_tasks_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_claim_tasks_assignee_due", "organization_id", "assignee_id", "due_date"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    requirement_id: Mapped[UUID | None] = mapped_column(ForeignKey("claim_document_requirements.id", ondelete="SET NULL"), nullable=True, index=True)
    request_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_request_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    completed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType, name="claim_task_type", native_enum=True, values_callable=enum_values), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="claim_task_status", native_enum=True, values_callable=enum_values), nullable=False, default=TaskStatus.OPEN, server_default=TaskStatus.OPEN.value)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority, name="claim_task_priority", native_enum=True, values_callable=enum_values), nullable=False, default=TaskPriority.MEDIUM, server_default=TaskPriority.MEDIUM.value)
    source: Mapped[TaskSource] = mapped_column(Enum(TaskSource, name="claim_task_source", native_enum=True, values_callable=enum_values), nullable=False, default=TaskSource.HUMAN, server_default=TaskSource.HUMAN.value)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RequestBatchStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT_EXTERNALLY = "sent_externally"
    CANCELLED = "cancelled"


class DocumentRequestBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_request_batches"
    __table_args__ = (Index("ix_doc_request_batches_org_claim", "organization_id", "claim_id", "created_at"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    recipient_label: Mapped[str | None] = mapped_column(String(180), nullable=True)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    draft_body: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[RequestBatchStatus] = mapped_column(Enum(RequestBatchStatus, name="document_request_batch_status", native_enum=True, values_callable=enum_values), nullable=False, default=RequestBatchStatus.DRAFT, server_default=RequestBatchStatus.DRAFT.value)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
