import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values

if TYPE_CHECKING:
    from app.modules.claims.models import Claim
    from app.modules.organizations.models import Organization
    from app.modules.users.models import User


class DocumentProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class ConfidentialityLevel(str, enum.Enum):
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class DocumentMalwareScanStatus(str, enum.Enum):
    LEGACY_UNSCANNED = "legacy_unscanned"
    CLEAN = "clean"
    INFECTED_QUARANTINED = "infected_quarantined"
    SCAN_ERROR = "scan_error"


class QuarantineStatus(str, enum.Enum):
    INFECTED = "infected"
    SCAN_ERROR = "scan_error"
    RELEASED = "released"
    PURGED = "purged"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "file_hash", name="uq_documents_claim_hash"),
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "document_family_id",
            "version_number",
            name="uq_documents_family_version",
        ),
        Index("ix_documents_org_claim", "organization_id", "claim_id"),
        Index("ix_documents_org_processing", "organization_id", "processing_status"),
        Index("ix_documents_org_family", "organization_id", "claim_id", "document_family_id"),
        Index(
            "uq_documents_active_family",
            "organization_id",
            "claim_id",
            "document_family_id",
            unique=True,
            postgresql_where=text("is_current AND deleted_at IS NULL"),
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    uploaded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    document_family_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    replacement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        Enum(DocumentProcessingStatus, name="document_processing_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=DocumentProcessingStatus.UPLOADED,
        server_default=DocumentProcessingStatus.UPLOADED.value,
    )
    confidentiality_level: Mapped[ConfidentialityLevel] = mapped_column(
        Enum(ConfidentialityLevel, name="confidentiality_level", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ConfidentialityLevel.CONFIDENTIAL,
        server_default=ConfidentialityLevel.CONFIDENTIAL.value,
    )
    malware_scan_status: Mapped[DocumentMalwareScanStatus] = mapped_column(
        Enum(
            DocumentMalwareScanStatus,
            name="document_malware_scan_status",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=DocumentMalwareScanStatus.LEGACY_UNSCANNED,
        server_default=DocumentMalwareScanStatus.LEGACY_UNSCANNED.value,
    )
    malware_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="documents")
    claim: Mapped["Claim"] = relationship(back_populates="documents")
    uploaded_by: Mapped["User | None"] = relationship(foreign_keys=[uploaded_by_id])
    superseded_by: Mapped["User | None"] = relationship(foreign_keys=[superseded_by_id])
    supersedes: Mapped["Document | None"] = relationship(
        remote_side="Document.id",
        uselist=False,
        foreign_keys=[supersedes_document_id],
    )


class QuarantinedUpload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quarantined_uploads"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "file_hash",
            name="uq_quarantined_uploads_claim_hash",
        ),
        Index("ix_quarantined_uploads_org_claim", "organization_id", "claim_id"),
        Index("ix_quarantined_uploads_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    uploaded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    replaces_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quarantine_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[QuarantineStatus] = mapped_column(
        Enum(QuarantineStatus, name="malware_quarantine_status", native_enum=True, values_callable=enum_values),
        nullable=False,
    )
    threat_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    replacement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_retried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidentiality_level: Mapped[ConfidentialityLevel] = mapped_column(
        Enum(ConfidentialityLevel, name="confidentiality_level", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ConfidentialityLevel.CONFIDENTIAL,
        server_default=ConfidentialityLevel.CONFIDENTIAL.value,
    )
