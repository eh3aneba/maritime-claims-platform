from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class TechnicalEvidenceItem(BaseModel):
    extraction_id: UUID | None = None
    field_path: str
    value: Any
    document_id: UUID | None = None
    source_quote: str | None = None
    source_locator_type: str | None = None
    source_locator_value: str | None = None
    source_verified: bool | None = None


class TechnicalMatrixRow(BaseModel):
    key: str
    title: str
    severity: str
    status: str
    evidence_for: list[Any]
    evidence_against: list[Any]
    unknown_or_missing: list[str]
    recommended_follow_up: list[str]
    explanation: str


class TechnicalReviewResponse(BaseModel):
    maintenance_facts: dict[str, Any]
    workshop_findings: list[TechnicalEvidenceItem]
    workshop_repair_options: list[TechnicalEvidenceItem]
    workshop_cause_opinions: list[TechnicalEvidenceItem]
    matrix: list[TechnicalMatrixRow]
    generated_at: datetime
