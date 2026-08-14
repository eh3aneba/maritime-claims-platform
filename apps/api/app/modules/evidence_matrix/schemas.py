from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


EvidenceMatrixRowStatus = Literal[
    "supported",
    "conflict_open",
    "conflict_reviewed",
    "source_superseded",
    "source_deleted",
    "unsupported",
    "conflict_only",
]


class EvidenceMatrixSource(BaseModel):
    extraction_id: UUID
    document_id: UUID
    document_family_id: UUID
    document_name: str
    document_type: str | None
    document_version: int
    document_is_current: bool
    document_deleted: bool
    authoritative: bool
    semantic_kind: str
    human_status: str
    source_verified: bool
    source_locator_type: str | None
    source_locator_value: str | None
    source_quote: str | None


class EvidenceMatrixConflict(BaseModel):
    id: UUID
    topic: str
    conflict_type: str
    description: str
    value_a: Any
    value_b: Any
    difference_minutes: Decimal | None
    materiality: str
    status: str
    resolution_note: str | None
    evidence_a_extraction_id: UUID | None
    evidence_b_extraction_id: UUID | None


class EvidenceMatrixRow(BaseModel):
    row_key: str
    topic: str
    field_path: str | None
    fact_id: UUID | None
    fact_value: Any
    fact_version: int | None
    approved_at: datetime | None
    supporting_evidence: list[EvidenceMatrixSource]
    conflicting_evidence: list[EvidenceMatrixConflict]
    status: EvidenceMatrixRowStatus


class EvidenceMatrixSummary(BaseModel):
    approved_fact_count: int
    matrix_row_count: int
    supporting_source_count: int
    current_source_document_count: int
    historical_source_document_count: int
    open_conflict_count: int
    reviewed_conflict_count: int
    superseded_fact_source_count: int


class EvidenceMatrixResponse(BaseModel):
    claim_id: UUID
    generated_at: datetime
    rows: list[EvidenceMatrixRow]
    summary: EvidenceMatrixSummary
