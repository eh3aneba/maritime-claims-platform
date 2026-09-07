from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
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
        Index(
            "ix_auth_sessions_oidc_source",
            "external_identity_provider_id",
            "external_identity_binding_id",
        ),
        UniqueConstraint(
            "oidc_authorization_transaction_id",
            name="uq_auth_sessions_oidc_authorization_transaction",
        ),
        UniqueConstraint(
            "saml_authn_transaction_id",
            name="uq_auth_sessions_saml_authn_transaction",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    identity_source: Mapped[str] = mapped_column(String(50), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(50), nullable=False)
    external_identity_provider_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("enterprise_identity_providers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    external_identity_binding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_identity_bindings.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    oidc_authorization_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("oidc_authorization_transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    saml_authn_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("saml_authn_transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
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
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)
    issuer_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("enterprise_identity_providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class OidcTrustProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable public verification policy pinned for one governed OIDC provider."""

    __tablename__ = "oidc_trust_profiles"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "profile_number",
            name="uq_oidc_trust_profiles_provider_number",
        ),
        UniqueConstraint(
            "provider_id",
            "profile_hash",
            name="uq_oidc_trust_profiles_provider_hash",
        ),
        Index(
            "ix_oidc_trust_profiles_org_provider_number",
            "organization_id",
            "provider_id",
            "profile_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("enterprise_identity_providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issuer_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    audience: Mapped[str] = mapped_column(String(500), nullable=False)
    jwks_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    allowed_algorithms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class OidcRuntimeProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable public runtime/client policy pinned to one OIDC trust source."""

    __tablename__ = "oidc_runtime_profiles"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "runtime_profile_number",
            name="uq_oidc_runtime_profiles_provider_number",
        ),
        UniqueConstraint(
            "provider_id",
            "runtime_profile_hash",
            name="uq_oidc_runtime_profiles_provider_hash",
        ),
        Index(
            "ix_oidc_runtime_profiles_org_provider_number",
            "organization_id",
            "provider_id",
            "runtime_profile_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("enterprise_identity_providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trust_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("oidc_trust_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trust_profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trust_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_endpoint: Mapped[str] = mapped_column(String(1000), nullable=False)
    token_endpoint: Mapped[str] = mapped_column(String(1000), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    client_auth_method: Mapped[str] = mapped_column(String(40), nullable=False)
    runtime_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_runtime_profile_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class OidcAuthorizationTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Short-lived OIDC transaction with hashed proof and pinned trust/runtime sources."""

    __tablename__ = "oidc_authorization_transactions"
    __table_args__ = (
        UniqueConstraint(
            "state_hash", name="uq_oidc_authorization_transactions_state_hash"
        ),
        Index(
            "ix_oidc_authorization_transactions_org_provider_lifecycle",
            "organization_id",
            "provider_id",
            "expires_at",
            "consumed_at",
            "cancelled_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("enterprise_identity_providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trust_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("oidc_trust_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trust_profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trust_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("oidc_runtime_profiles.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    runtime_profile_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pkce_code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    pkce_method: Mapped[str] = mapped_column(
        String(10), nullable=False, default="S256", server_default="S256"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
