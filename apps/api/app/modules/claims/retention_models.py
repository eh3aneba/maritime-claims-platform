from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TenantRetentionPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable tenant-scoped retention policy version.

    Policy rows are append-only at the application layer. The latest version is
    authoritative; a latest version with ``enabled=False`` disables disposal
    eligibility without mutating prior policy history.
    """

    __tablename__ = "tenant_retention_policies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "policy_number",
            name="uq_tenant_retention_policies_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "policy_hash",
            name="uq_tenant_retention_policies_org_hash",
        ),
        CheckConstraint(
            "closed_claim_retention_days >= 30 AND closed_claim_retention_days <= 36500",
            name="ck_retention_policy_claim_days",
        ),
        CheckConstraint(
            "evidence_retention_days >= 30 AND evidence_retention_days <= 36500",
            name="ck_retention_policy_evidence_days",
        ),
        Index(
            "ix_tenant_retention_policies_org_number",
            "organization_id",
            "policy_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_claim_retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    disposal_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ClaimLegalHold(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only preservation instruction for one claim.

    Original hold fields are never changed through the application API. Release
    fields are filled once; released rows remain available for audit history.
    """

    __tablename__ = "claim_legal_holds"
    __table_args__ = (
        Index(
            "ix_claim_legal_holds_org_claim",
            "organization_id",
            "claim_id",
        ),
        Index(
            "ix_claim_legal_holds_org_claim_release",
            "organization_id",
            "claim_id",
            "released_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    placed_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
