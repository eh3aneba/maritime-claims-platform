from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MfaRecoveryCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-way stored, single-use recovery credential bound to one TOTP factor."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        UniqueConstraint(
            "factor_id",
            "batch_id",
            "position",
            name="uq_mfa_recovery_codes_factor_batch_position",
        ),
        UniqueConstraint(
            "code_digest",
            name="uq_mfa_recovery_codes_digest",
        ),
        Index(
            "ix_mfa_recovery_codes_org_user_lifecycle",
            "organization_id",
            "user_id",
            "factor_id",
            "consumed_at",
            "invalidated_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    factor_id: Mapped[UUID] = mapped_column(
        ForeignKey("totp_mfa_factors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_auth_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_by_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
