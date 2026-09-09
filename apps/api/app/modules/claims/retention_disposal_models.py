from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DisposalAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Human-governed, non-destructive authorization work item.

    This record captures the exact retention/evidence state reviewed by one
    local Admin and requires a distinct local Admin to approve it. Approval is
    authority for a later, separately governed disposal executor only; this
    model does not mutate or delete claim/evidence content.
    """

    __tablename__ = "disposal_authorizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_disposal_authorization_status",
        ),
        CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NULL) OR "
            "(status = 'approved' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NOT NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NOT NULL AND rejected_at IS NOT NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NOT NULL) OR "
            "(status IN ('expired', 'invalidated') AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NOT NULL "
            "AND invalidated_at IS NOT NULL AND decision_reason IS NOT NULL)",
            name="ck_disposal_authorization_lifecycle",
        ),
        CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_disposal_authorization_four_eyes",
        ),
        Index(
            "ix_disposal_authorizations_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_disposal_authorizations_org_status_expiry",
            "organization_id",
            "status",
            "authorization_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    retention_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_retention_policies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    claim_retention_anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claim_retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_retention_anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligibility_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligibility_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    active_hold_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pending_proposal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval"
    )

    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
