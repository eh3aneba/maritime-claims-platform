from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WebAuthnCredentialResetRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Four-eyes reset and bounded re-enrollment authorization for one WebAuthn credential."""

    __tablename__ = "webauthn_credential_reset_requests"
    __table_args__ = (
        Index(
            "uq_webauthn_credential_reset_requests_credential_open",
            "credential_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
            sqlite_where=text("status IN ('pending', 'approved')"),
        ),
        Index(
            "ix_webauthn_credential_reset_requests_org_lifecycle",
            "organization_id",
            "user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_webauthn_credential_reset_requests_reenrollment",
            "organization_id",
            "user_id",
            "reenrollment_expires_at",
            "reenrollment_consumed_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("webauthn_credentials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_auth_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rejected_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cancelled_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    executed_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    reenrollment_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    reenrollment_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reenrollment_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reenrollment_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reenrollment_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("webauthn_credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )
