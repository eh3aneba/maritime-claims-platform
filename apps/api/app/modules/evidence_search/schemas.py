from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=50)
    retrieval_mode: Literal["lexical"] = "lexical"
    include_superseded: bool = False
    document_types: list[str] = Field(default_factory=list, max_length=30)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    exact_phrase: bool = False


class EvidenceSearchResult(BaseModel):
    search_unit_id: UUID
    segment_id: UUID
    document_id: UUID
    extraction_id: UUID
    document_family_id: UUID
    document_filename: str
    document_type: str | None
    document_version: int
    is_current_document: bool
    locator_type: str
    locator_value: str
    confidentiality_level: str
    snippet: str
    lexical_score: float
    semantic_score: float | None = None
    combined_score: float
    match_reasons: list[str]
    source_file_hash: str
    extraction_text_hash: str | None
    normalized_text_hash: str
    search_unit_hash: str


class EvidenceSearchResponse(BaseModel):
    claim_id: UUID
    run_id: UUID
    retrieval_mode: str
    ranking_version: str
    query_hash: str
    filters_hash: str
    result_set_hash: str
    result_count: int
    no_sufficient_evidence_found: bool
    results: list[EvidenceSearchResult]
