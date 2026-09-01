from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ClaimQaSynthesisRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free operational lineage for governed Claim Q&A synthesis.

    Raw questions, retrieved passages, model output text and source quotations
    are deliberately excluded. Only hashes, identifiers and operational metrics
    required for auditability/governance are persisted.
    """

    __tablename__ = "claim_qa_synthesis_runs"
    __table_args__ = (
        Index("ix_claim_qa_synthesis_scope", "organization_id", "claim_id", "created_at"),
        Index("ix_claim_qa_synthesis_authorization", "production_authorization_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retrieval_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claim_evidence_search_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    production_authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_production_wide_authorizations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_call_made: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_bundle_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schema_bundle_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    authorization_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eligibility_policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_unit_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_response_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
