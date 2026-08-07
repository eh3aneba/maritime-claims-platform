from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.tasks.models import RequestBatchStatus, TaskPriority, TaskSource, TaskStatus, TaskType


class ClaimTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    requirement_id: UUID | None
    request_batch_id: UUID | None
    assignee_id: UUID | None
    title: str
    description: str | None
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    source: TaskSource
    due_date: date | None
    completed_at: datetime | None
    completion_reason: str | None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[ClaimTaskResponse]
    total: int


class DocumentRequestCreate(BaseModel):
    requirement_ids: list[UUID] = Field(default_factory=list)
    all_critical: bool = False
    due_date: date | None = None
    recipient_label: str | None = Field(default="Shipowner / Assured", max_length=180)
    assignee_id: UUID | None = None

    @model_validator(mode="after")
    def require_selection(self):
        if not self.all_critical and not self.requirement_ids:
            raise ValueError("Select one or more requirements or set all_critical=true")
        return self


class DocumentRequestBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_id: UUID
    recipient_label: str | None
    subject: str
    draft_body: str
    requirement_ids: list
    status: RequestBatchStatus
    due_date: date | None
    created_at: datetime


class DocumentRequestResult(BaseModel):
    batch: DocumentRequestBatchResponse
    tasks: list[ClaimTaskResponse]


class TaskCompleteRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
