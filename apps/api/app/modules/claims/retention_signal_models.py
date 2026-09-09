from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PreservationSignalProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-scoped trust profile for signed preservation-signal intake.

    Raw signing key material is never persisted. The application derives the
    active key from the application master secret plus this profile's non-secret
    salt/version tuple. Profiles are disabled by default.
    """

    __tablename__ = "preservation_signal_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_psp_org_name"),
        Index("ix_psp_org_enabled", "organization_id", "enabled", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    updated_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    allowed_hold_sources: Mapped[list] = mapped_column(JSON, nullable=False)

    secret_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    secret_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    previous_secret_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_secret_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_secret_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
