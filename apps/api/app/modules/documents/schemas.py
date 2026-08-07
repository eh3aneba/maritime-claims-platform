from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.documents.models import ConfidentialityLevel, DocumentProcessingStatus


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
    version_number: int
    processing_status: DocumentProcessingStatus
    confidentiality_level: ConfidentialityLevel
    uploaded_by_id: UUID | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentUploadMetadata(BaseModel):
    document_type: str | None = Field(default=None, max_length=100)
    confidentiality_level: ConfidentialityLevel = ConfidentialityLevel.CONFIDENTIAL
