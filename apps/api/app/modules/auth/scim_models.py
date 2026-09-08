from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ScimProvisioningProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable tenant-scoped policy for a bounded SCIM provisioning client."""

    __tablename__ = "scim_provisioning_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "profile_number",
            name="uq_scim_provisioning_profiles_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "profile_hash",
            name="uq_scim_provisioning_profiles_org_hash",
        ),
        Index(
            "ix_scim_provisioning_profiles_org_number",
            "organization_id",
            "profile_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    client_name: Mapped[str] = mapped_column(String(160), nullable=False)
    service_base_path: Mapped[str] = mapped_column(String(160), nullable=False)
    token_ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ScimProvisioningToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-time-issued SCIM bearer credential stored only as a keyed digest."""

    __tablename__ = "scim_provisioning_tokens"
    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_scim_provisioning_tokens_digest",
        ),
        Index(
            "uq_scim_provisioning_tokens_profile_unrevoked",
            "profile_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_scim_provisioning_tokens_org_lifecycle",
            "organization_id",
            "expires_at",
            "revoked_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("scim_provisioning_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
