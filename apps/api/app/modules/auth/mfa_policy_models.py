from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MfaPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-scoped policy that constrains existing application authority with MFA."""

    __tablename__ = "mfa_policies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            name="uq_mfa_policies_organization_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    required_roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    updated_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
