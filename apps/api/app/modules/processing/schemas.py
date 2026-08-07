from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.processing.models import ProcessingJobStatus, ProcessingJobType


class ProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    job_type: ProcessingJobType
    status: ProcessingJobStatus
    attempt_count: int
    max_attempts: int
    last_error: str | None
    result: dict | None
    created_at: datetime
    completed_at: datetime | None


class TextExtractionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    extraction_method: str
    extractor_version: str
    char_count: int
    segment_count: int
    requires_ocr: bool
    text_hash: str | None
    warnings: list | None


class DocumentProcessingSummary(BaseModel):
    job: ProcessingJobResponse | None
    text_extraction: TextExtractionSummary | None
