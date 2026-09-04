from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.claims.schemas import ClaimCreate, ClaimRead
from app.modules.documents.models import DocumentMalwareScanStatus
from app.modules.intake.document_types import (
    DEFAULT_INTAKE_DOCUMENT_TYPE,
    INTAKE_DOCUMENT_TYPES,
    is_intake_document_type,
)
from app.modules.intake.models import ClaimIntakeStatus


class ClaimIntakeDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash: str
    malware_scan_status: DocumentMalwareScanStatus
    status: ClaimIntakeStatus
    extraction_method: str | None
    ocr_languages: str | None
    extraction_warnings: list[str] | None
    classification_candidate: str | None
    classification_confidence: int | None
    classification_rule: str | None
    extracted_fields: dict | None
    field_evidence: dict | None
    approved_claim_id: UUID | None
    source_document_id: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    uploaded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ClaimIntakeDraftList(BaseModel):
    items: list[ClaimIntakeDraftRead]
    total: int


class ClaimIntakeDocumentTypeRegistry(BaseModel):
    items: list[str]
    default: str
    unknown_requires_human_choice: bool = True

    @classmethod
    def current(cls) -> "ClaimIntakeDocumentTypeRegistry":
        return cls(items=list(INTAKE_DOCUMENT_TYPES), default=DEFAULT_INTAKE_DOCUMENT_TYPE)


class ClaimIntakeApprove(BaseModel):
    claim: ClaimCreate
    # Deliberately required: the server must never turn an omitted classifier
    # decision into authoritative claim evidence by choosing a default.
    document_type: str = Field(min_length=2, max_length=100)
    review_note: str = Field(min_length=10, max_length=2000)

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not is_intake_document_type(normalized):
            allowed = ", ".join(INTAKE_DOCUMENT_TYPES)
            raise ValueError(
                f"Select a controlled H&M document type before approval. Allowed values: {allowed}."
            )
        return normalized


class ClaimIntakeReject(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class ClaimIntakeApprovalResult(BaseModel):
    draft: ClaimIntakeDraftRead
    claim: ClaimRead
