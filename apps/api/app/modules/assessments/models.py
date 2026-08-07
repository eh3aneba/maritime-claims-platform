import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class AssessmentStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"


class AssessmentSectionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"


class InitialAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "initial_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "version", name="uq_initial_assessment_version"),
        Index("ix_initial_assessment_org_claim", "organization_id", "claim_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AssessmentStatus] = mapped_column(Enum(AssessmentStatus, name="initial_assessment_status", native_enum=True, values_callable=enum_values), nullable=False, default=AssessmentStatus.DRAFT, server_default=AssessmentStatus.DRAFT.value)
    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_state: Mapped[str] = mapped_column(String(30), nullable=False)
    blocking_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_preliminary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    generation_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assessment_sections"
    __table_args__ = (
        UniqueConstraint("assessment_id", "section_key", name="uq_assessment_section_key"),
        Index("ix_assessment_sections_assessment_order", "assessment_id", "sort_order"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("initial_assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    section_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    approved_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AssessmentSectionStatus] = mapped_column(Enum(AssessmentSectionStatus, name="assessment_section_status", native_enum=True, values_callable=enum_values), nullable=False, default=AssessmentSectionStatus.PENDING, server_default=AssessmentSectionStatus.PENDING.value)
    source_manifest: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
