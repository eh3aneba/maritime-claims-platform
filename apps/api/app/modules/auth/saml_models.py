from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SamlTrustRuntimeProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable public SAML trust/runtime policy for one governed provider."""

    __tablename__ = "saml_trust_runtime_profiles"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "profile_number",
            name="uq_saml_trust_runtime_profiles_provider_number",
        ),
        UniqueConstraint(
            "provider_id",
            "profile_hash",
            name="uq_saml_trust_runtime_profiles_provider_hash",
        ),
        Index(
            "ix_saml_trust_runtime_profiles_org_provider_number",
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
    idp_entity_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    idp_sso_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    sp_entity_id: Mapped[str] = mapped_column(String(500), nullable=False)
    acs_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    authn_request_binding: Mapped[str] = mapped_column(String(40), nullable=False)
    response_binding: Mapped[str] = mapped_column(String(40), nullable=False)
    allowed_signature_algorithms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_digest_algorithms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    idp_signing_certificate_pem: Mapped[str] = mapped_column(Text, nullable=False)
    certificate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class SamlAuthnTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Short-lived SAML AuthnRequest correlation bound to one immutable profile."""

    __tablename__ = "saml_authn_transactions"
    __table_args__ = (
        UniqueConstraint(
            "request_id_hash",
            name="uq_saml_authn_transactions_request_id_hash",
        ),
        UniqueConstraint(
            "relay_state_hash",
            name="uq_saml_authn_transactions_relay_state_hash",
        ),
        Index(
            "ix_saml_authn_transactions_org_provider_lifecycle",
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
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("saml_trust_runtime_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    relay_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
