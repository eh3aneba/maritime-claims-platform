from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, event, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


_PROVENANCE_CHECK = (
    "(provenance_kind = 'ai_review' AND source_extraction_id IS NOT NULL AND source_text_extraction_id IS NULL) "
    "OR (provenance_kind = 'intake_review' AND source_extraction_id IS NULL AND source_text_extraction_id IS NOT NULL)"
)


class ClaimFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current human-approved structured fact for a claim.

    Candidates never write here directly. A fact is canonical only after an
    explicit human review action. AI-reviewed facts retain their
    ``DocumentExtraction`` lineage while intake-reviewed facts point to the real
    ``DocumentTextExtraction`` created from the approved source document.
    """

    __tablename__ = "claim_facts"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "field_path", name="uq_claim_facts_org_claim_field"),
        Index("ix_claim_facts_org_claim", "organization_id", "claim_id"),
        CheckConstraint("version >= 1", name="ck_claim_facts_version"),
        CheckConstraint(_PROVENANCE_CHECK, name="ck_claim_facts_provenance_lineage"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    field_path: Mapped[str] = mapped_column(String(220), nullable=False)
    value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    provenance_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="ai_review", server_default="ai_review")
    source_extraction_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_text_extraction_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_extractions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_segment_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_segments.id", ondelete="SET NULL"), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")


class ClaimFactRevision(UUIDPrimaryKeyMixin, Base):
    """Append-only snapshot of each canonical ClaimFact state.

    The current row in ``claim_facts`` remains the fast downstream read model.
    Revisions preserve the full authoritative lineage needed to explain
    supersession and safely restore the last still-valid human-approved fact when
    a newer AI extraction is later rejected.
    """

    __tablename__ = "claim_fact_revisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "field_path",
            "version",
            name="uq_claim_fact_revisions_org_claim_field_version",
        ),
        Index("ix_claim_fact_revisions_org_claim_field", "organization_id", "claim_id", "field_path"),
        CheckConstraint("version >= 1", name="ck_claim_fact_revisions_version"),
        CheckConstraint(_PROVENANCE_CHECK, name="ck_claim_fact_revisions_provenance_lineage"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    field_path: Mapped[str] = mapped_column(String(220), nullable=False)
    value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    provenance_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_extraction_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_text_extraction_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_extractions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_segment_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_text_segments.id", ondelete="SET NULL"), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


@event.listens_for(Session, "before_flush")
def append_claim_fact_revisions(session: Session, _flush_context, _instances) -> None:
    """Persist one immutable revision for every new/changed canonical fact.

    Keeping this at the ORM boundary means deterministic intake review and AI
    review share the same history semantics instead of relying on each caller to
    remember to snapshot the current fact.
    """

    candidates = [obj for obj in session.new if isinstance(obj, ClaimFact)]
    candidates.extend(
        obj
        for obj in session.dirty
        if isinstance(obj, ClaimFact) and session.is_modified(obj, include_collections=False)
    )
    if not candidates:
        return

    pending_keys = {
        (row.organization_id, row.claim_id, row.field_path, row.version)
        for row in session.new
        if isinstance(row, ClaimFactRevision)
    }
    for fact in candidates:
        version = fact.version or 1
        key = (fact.organization_id, fact.claim_id, fact.field_path, version)
        if key in pending_keys:
            continue
        provenance_kind = fact.provenance_kind or "ai_review"
        approved_at = fact.approved_at or datetime.now(UTC)
        session.add(
            ClaimFactRevision(
                organization_id=fact.organization_id,
                claim_id=fact.claim_id,
                field_path=fact.field_path,
                value=fact.value,
                provenance_kind=provenance_kind,
                source_extraction_id=fact.source_extraction_id,
                source_text_extraction_id=fact.source_text_extraction_id,
                source_document_id=fact.source_document_id,
                source_segment_id=fact.source_segment_id,
                approved_by_id=fact.approved_by_id,
                approved_at=approved_at,
                version=version,
            )
        )
        pending_keys.add(key)
