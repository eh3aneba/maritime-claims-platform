from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

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

    @computed_field
    @property
    def source_text_quality_state(self) -> Literal[
        "ocr_human_source_comparison_required", "not_an_ocr_extraction"
    ]:
        """OCR completion is text availability, never source-text accuracy.

        Missing negations, dates or engineering qualifiers cannot be
        detected from an OCR transcript alone. This is a deterministic
        disclosure for the operator, not a verification/approval flag.
        """
        if "tesseract:" in self.extraction_method.lower():
            return "ocr_human_source_comparison_required"
        return "not_an_ocr_extraction"


class OperatorProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    job_type: ProcessingJobType
    status: ProcessingJobStatus
    attempt_count: int
    max_attempts: int
    created_at: datetime
    completed_at: datetime | None


class DocumentProcessingSummary(BaseModel):
    job: OperatorProcessingJobResponse | None
    text_extraction: TextExtractionSummary | None
    operator_status: Literal["uploaded", "queued", "running", "completed", "failed"]
    can_retry: bool
    retry_recommended: bool
    processing_release_required: bool
    processing_release_status: Literal["not_applicable", "required", "active", "revoked"]

# Read-only, bounded source comparison. Text here is a machine transcript
# and carries NO approval, correction or semantic-negation guarantee.
class SourceExtractionSegment(BaseModel):
    segment_index: int
    locator_type: str
    locator_value: str
    text_preview: str
    source_char_count: int
    text_truncated: bool


class SourceExtractionSegmentsResponse(BaseModel):
    document_id: UUID
    document_version: int
    source_file_hash: str
    extraction_text_hash: str | None
    extraction_method: str
    source_text_quality_state: Literal[
        "ocr_human_source_comparison_required", "not_an_ocr_extraction"
    ]
    review_disposition: Literal["machine_unverified"]
    total_segments: int
    offset: int
    limit: int
    segments: list[SourceExtractionSegment]
