from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ClaimFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current human-approved structured fact for a claim.

    AI candidates never write here directly. Only an explicit human review action
    may create/update a record. Review history remains append-only in ai_feedback.
    """

    __tablename__ = "claim_facts"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "field_path", name="uq_claim_facts_org_claim_field"),
        Index("ix_claim_facts_org_claim", "organization_id", "claim_id"),
        CheckConstraint("version >= 1", name="ck_claim_facts_version"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    field_path: Mapped[str] = mapped_column(String(220), nullable=False)
    value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    source_extraction_id: Mapped[UUID] = mapped_column(ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_segment_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_segments.id", ondelete="SET NULL"), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
