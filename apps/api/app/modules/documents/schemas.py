from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.documents.models import (
    ConfidentialityLevel,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
    QuarantineStatus,
)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    filename: str
    original_filename: str
    document_type: str | None
    mime_type: str
    file_size_bytes: int
    file_hash: str
    document_family_id: UUID
    supersedes_document_id: UUID | None
    version_number: int
    is_current: bool
    replacement_reason: str | None
    superseded_at: datetime | None
    superseded_by_id: UUID | None
    processing_status: DocumentProcessingStatus
    confidentiality_level: ConfidentialityLevel
    malware_scan_status: DocumentMalwareScanStatus
    malware_scanned_at: datetime | None
    uploaded_by_id: UUID | None
    created_at: datetime


class QuarantinedUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    source_document_id: UUID | None
    replaces_document_id: UUID | None
    replacement_reason: str | None
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash: str
    status: QuarantineStatus
    threat_name: str | None
    scanned_at: datetime
    retry_count: int
    last_retried_at: datetime | None
    uploaded_by_id: UUID | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    quarantined_items: list[QuarantinedUploadResponse] = Field(default_factory=list)
    quarantined_total: int = 0


class DocumentUploadMetadata(BaseModel):
    document_type: str | None = Field(default=None, max_length=100)
    confidentiality_level: ConfidentialityLevel = ConfidentialityLevel.CONFIDENTIAL


class LegacyRescanRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=25)


class LegacyRescanJobResponse(BaseModel):
    job_id: UUID
    document_id: UUID
    status: str


class LegacyRescanResponse(BaseModel):
    queued_count: int
    skipped_count: int
    jobs: list[LegacyRescanJobResponse]


class QuarantineRetryResponse(BaseModel):
    quarantine_id: UUID
    status: QuarantineStatus
    retry_count: int
    released_document_id: UUID | None
    threat_name: str | None


class QuarantinePurgeRequest(BaseModel):
    confirm_upload_id: UUID
    reason: str = Field(min_length=20, max_length=1000)


class QuarantinePurgeResponse(BaseModel):
    quarantine_id: UUID
    status: QuarantineStatus
