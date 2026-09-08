from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SamlMfaAssuranceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable policy mapping signed SAML AuthnContext to MFA assurance."""

    __tablename__ = "saml_mfa_assurance_profiles"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "profile_number",
            name="uq_saml_mfa_assurance_provider_number",
        ),
        UniqueConstraint(
            "provider_id",
            "profile_hash",
            name="uq_saml_mfa_assurance_provider_hash",
        ),
        Index(
            "ix_saml_mfa_assurance_org_provider_number",
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
    saml_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("saml_trust_runtime_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    saml_profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    saml_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    accepted_authn_context_values: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
