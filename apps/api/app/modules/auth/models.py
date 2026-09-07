from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AuthSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Server-side authentication session with bounded identity provenance."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_org_user", "organization_id", "user_id"),
        Index(
            "ix_auth_sessions_org_lifecycle",
            "organization_id",
            "revoked_at",
            "expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    identity_source: Mapped[str] = mapped_column(String(50), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(50), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class EnterpriseIdentityProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-scoped public identity-provider registry entry."""

    __tablename__ = "enterprise_identity_providers"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider_key",
            name="uq_enterprise_identity_providers_org_key",
        ),
        UniqueConstraint(
            "organization_id",
            "protocol",
            "issuer_identifier",
            name="uq_enterprise_identity_providers_org_protocol_issuer",
        ),
        Index(
            "ix_enterprise_identity_providers_org_enabled",
            "organization_id",
            "is_enabled",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)
    issuer_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )


class ExternalIdentityBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historical binding between one external subject fingerprint and an app User."""

    __tablename__ = "external_identity_bindings"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "subject_fingerprint",
            name="uq_external_identity_bindings_provider_subject",
        ),
        Index(
            "uq_external_identity_bindings_provider_user_active",
            "provider_id",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_external_identity_bindings_org_lifecycle",
            "organization_id",
            "revoked_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("enterprise_identity_providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subject_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
