from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OidcMfaAssuranceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable tenant/provider-scoped policy for signed OIDC MFA claim equivalence."""

    __tablename__ = "oidc_mfa_assurance_profiles"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "profile_number",
            name="uq_oidc_mfa_assurance_provider_number",
        ),
        UniqueConstraint(
            "provider_id",
            "profile_hash",
            name="uq_oidc_mfa_assurance_provider_hash",
        ),
        Index(
            "ix_oidc_mfa_assurance_org_provider_number",
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
    trust_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("oidc_trust_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trust_profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trust_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    accepted_amr_values: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    accepted_acr_values: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class OidcMfaAssuranceBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-to-one immutable source pin plus bounded verified evidence for an OIDC transaction."""

    __tablename__ = "oidc_mfa_assurance_bindings"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id",
            name="uq_oidc_mfa_assurance_binding_transaction",
        ),
        Index(
            "ix_oidc_mfa_assurance_binding_org_provider",
            "organization_id",
            "provider_id",
            "transaction_id",
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
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("oidc_authorization_transactions.id", ondelete="RESTRICT"),
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
    assurance_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("oidc_mfa_assurance_profiles.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assurance_profile_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assurance_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
