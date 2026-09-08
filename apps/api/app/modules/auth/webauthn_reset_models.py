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
            "uq_wacr_credential_open",
            "credential_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
            sqlite_where=text("status IN ('pending', 'approved')"),
        ),
        Index(
            "ix_wacr_org_lifecycle",
            "organization_id",
            "user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_wacr_reenrollment",
            "organization_id",
            "user_id",
            "reenrollment_expires_at",
            "reenrollment_consumed_at",
        ),
        Index("ix_wacr_org", "organization_id"),
        Index("ix_wacr_user", "user_id"),
        Index("ix_wacr_credential", "credential_id"),
        Index("ix_wacr_requester", "requested_by_id"),
        Index("ix_wacr_request_session", "requested_auth_session_id"),
        Index("ix_wacr_status", "status"),
        Index("ix_wacr_approver", "approved_by_id"),
        Index("ix_wacr_approve_session", "approved_auth_session_id"),
        Index("ix_wacr_rejector", "rejected_by_id"),
        Index("ix_wacr_reject_session", "rejected_auth_session_id"),
        Index("ix_wacr_canceller", "cancelled_by_id"),
        Index("ix_wacr_cancel_session", "cancelled_auth_session_id"),
        Index("ix_wacr_executor", "executed_by_id"),
        Index("ix_wacr_execute_session", "executed_auth_session_id"),
        Index("ix_wacr_reenroll_expiry", "reenrollment_expires_at"),
        Index("ix_wacr_reenroll_session", "reenrollment_auth_session_id"),
        Index("ix_wacr_replacement", "reenrollment_credential_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("webauthn_credentials.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    requested_auth_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
    )

    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
    )

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    executed_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
    )

    reenrollment_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reenrollment_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reenrollment_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
    )
    reenrollment_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reenrollment_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("webauthn_credentials.id", ondelete="SET NULL"), nullable=True
    )
