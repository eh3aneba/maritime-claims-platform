import enum
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class ClaimPackFormat(str, enum.Enum):
    PDF = "pdf"
    XLSX = "xlsx"


class ClaimPackExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_pack_exports"
    __table_args__ = (
        Index(
            "ix_claim_pack_exports_org_claim_created",
            "organization_id",
            "claim_id",
            "created_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    generated_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    export_format: Mapped[ClaimPackFormat] = mapped_column(
        Enum(
            ClaimPackFormat,
            name="claim_pack_format",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    snapshot_schema_version: Mapped[str] = mapped_column(
        String(30), nullable=False, default="1.0", server_default="1.0"
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
