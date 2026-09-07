from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
