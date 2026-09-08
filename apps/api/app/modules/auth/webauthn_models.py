from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WebAuthnRelyingPartyProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable tenant-scoped WebAuthn relying-party policy."""

    __tablename__ = "webauthn_relying_party_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "profile_number",
            name="uq_webauthn_rp_profiles_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "profile_hash",
            name="uq_webauthn_rp_profiles_org_hash",
        ),
        Index(
            "ix_webauthn_rp_profiles_org_number",
            "organization_id",
            "profile_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rp_id: Mapped[str] = mapped_column(String(253), nullable=False)
    rp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    user_verification: Mapped[str] = mapped_column(String(20), nullable=False)
    attestation: Mapped[str] = mapped_column(String(20), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class WebAuthnRegistrationTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Short-lived one-time WebAuthn registration challenge custody."""

    __tablename__ = "webauthn_registration_transactions"
    __table_args__ = (
        UniqueConstraint(
            "challenge_hash",
            name="uq_webauthn_registration_transactions_challenge_hash",
        ),
        Index(
            "uq_webauthn_registration_transactions_session_open",
            "auth_session_id",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND cancelled_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND cancelled_at IS NULL"),
        ),
        Index(
            "ix_webauthn_registration_transactions_org_user_lifecycle",
            "organization_id",
            "user_id",
            "expires_at",
            "consumed_at",
            "cancelled_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    auth_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("webauthn_relying_party_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebAuthnAuthenticationTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Short-lived one-time WebAuthn assertion challenge custody."""

    __tablename__ = "webauthn_authentication_transactions"
    __table_args__ = (
        UniqueConstraint(
            "challenge_hash",
            name="uq_webauthn_authentication_transactions_challenge_hash",
        ),
        Index(
            "uq_webauthn_authentication_transactions_session_open",
            "auth_session_id",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND cancelled_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND cancelled_at IS NULL"),
        ),
        Index(
            "ix_webauthn_authentication_transactions_org_user_lifecycle",
            "organization_id",
            "user_id",
            "expires_at",
            "consumed_at",
            "cancelled_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    auth_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("webauthn_relying_party_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebAuthnCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Verified WebAuthn credential custody without raw credential identifiers."""

    __tablename__ = "webauthn_credentials"
    __table_args__ = (
        UniqueConstraint("credential_id_hash", name="uq_webauthn_credentials_credential_hash"),
        UniqueConstraint(
            "registration_transaction_id",
            name="uq_webauthn_credentials_registration_transaction",
        ),
        Index(
            "ix_webauthn_credentials_org_user_lifecycle",
            "organization_id",
            "user_id",
            "revoked_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("webauthn_relying_party_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("webauthn_registration_transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credential_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[int] = mapped_column(Integer, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    aaguid: Mapped[str] = mapped_column(String(32), nullable=False)
    attestation_format: Mapped[str] = mapped_column(String(20), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
