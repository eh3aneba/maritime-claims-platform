from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClaimQaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: Literal["lexical", "hybrid"] = "hybrid"
    include_superseded: bool = False
    document_types: list[str] = Field(default_factory=list, max_length=30)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    exact_phrase: bool = False


class ClaimQaSourceRef(BaseModel):
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
    source_file_hash: str
    extraction_text_hash: str | None
    normalized_text_hash: str
    search_unit_hash: str


class ClaimQaStatement(BaseModel):
    statement_number: int
    text: str
    source_refs: list[ClaimQaSourceRef]
    statement_hash: str


class ClaimQaConflict(BaseModel):
    conflict_type: Literal["explicit_polarity", "numeric_disagreement"]
    detail: str
    statement_hashes: list[str]


class ClaimQaResponse(BaseModel):
    claim_id: UUID
    status: Literal["answered", "insufficient_evidence", "conflicting_evidence"]
    answer: str
    statements: list[ClaimQaStatement]
    conflicts: list[ClaimQaConflict]
    missing_evidence: list[str]
    retrieval_run_id: UUID
    retrieval_mode: str
    ranking_version: str
    question_hash: str
    result_set_hash: str
    semantic_used: bool
    semantic_provider: str | None
    semantic_model: str | None
    semantic_authorization_hash: str | None
    answer_engine_version: str
    answer_hash: str
    non_authoritative: bool = True
    human_review_required: bool = True
    claim_facts_updated: bool = False
    disclaimer: str
