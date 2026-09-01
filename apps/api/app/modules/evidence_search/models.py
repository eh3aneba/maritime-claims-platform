from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ClaimEvidenceSearchUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_evidence_search_units"
    __table_args__ = (
        UniqueConstraint("segment_id", "index_version", name="uq_claim_evidence_search_unit_segment_version"),
        Index(
            "ix_claim_evidence_search_units_scope",
            "organization_id",
            "claim_id",
            "is_current_document",
            "deactivated_at",
        ),
        Index("ix_claim_evidence_search_units_document", "document_id", "document_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_text_extractions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_text_segments.id", ondelete="CASCADE"), nullable=False, index=True
    )

    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current_document: Mapped[bool] = mapped_column(Boolean, nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidentiality_level: Mapped[str] = mapped_column(String(24), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_type: Mapped[str] = mapped_column(String(30), nullable=False)
    locator_value: Mapped[str] = mapped_column(String(100), nullable=False)
    index_version: Mapped[str] = mapped_column(String(30), nullable=False)
    search_unit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClaimEvidenceSearchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_evidence_search_runs"
    __table_args__ = (
        Index("ix_claim_evidence_search_runs_scope", "organization_id", "claim_id", "created_at"),
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

    normalized_query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    ranking_version: Mapped[str] = mapped_column(String(30), nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False)
    filters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_ledger: Mapped[list] = mapped_column(JSON, nullable=False)
    result_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    semantic_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    semantic_authorization_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
