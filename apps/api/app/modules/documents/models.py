import enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
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


class Document(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "file_hash", name="uq_documents_claim_hash"),
        Index("ix_documents_org_claim", "organization_id", "claim_id"),
        Index("ix_documents_org_processing", "organization_id", "processing_status"),
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

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
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

    organization: Mapped["Organization"] = relationship(back_populates="documents")
    claim: Mapped["Claim"] = relationship(back_populates="documents")
    uploaded_by: Mapped["User | None"] = relationship(foreign_keys=[uploaded_by_id])
    supersedes: Mapped["Document | None"] = relationship(remote_side="Document.id", uselist=False)
