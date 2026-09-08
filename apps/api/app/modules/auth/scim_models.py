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
    user_provisioning_enabled: Mapped[bool] = mapped_column(
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


class ScimUserProvisioningGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Local Admin authorization for one bounded SCIM User creation."""

    __tablename__ = "scim_user_provisioning_grants"
    __table_args__ = (
        UniqueConstraint("grant_hash", name="uq_scim_user_grants_hash"),
        Index(
            "uq_scim_user_grants_org_email_pending",
            "organization_id",
            "email_fingerprint",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND cancelled_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND cancelled_at IS NULL"),
        ),
        Index(
            "ix_scim_user_grants_org_lifecycle",
            "organization_id",
            "expires_at",
            "consumed_at",
            "cancelled_at",
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
    email_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    grant_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ScimUserBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-scoped lineage proving an application User was created through SCIM."""

    __tablename__ = "scim_user_bindings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_scim_user_bindings_org_user",
        ),
        UniqueConstraint(
            "organization_id",
            "external_id_fingerprint",
            name="uq_scim_user_bindings_org_external",
        ),
        UniqueConstraint("grant_id", name="uq_scim_user_bindings_grant"),
        Index(
            "ix_scim_user_bindings_org_lifecycle",
            "organization_id",
            "deactivated_at",
            "last_synced_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    grant_id: Mapped[UUID] = mapped_column(
        ForeignKey("scim_user_provisioning_grants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("scim_provisioning_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_name_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
