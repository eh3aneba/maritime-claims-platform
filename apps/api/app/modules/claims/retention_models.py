from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TenantRetentionPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable tenant-scoped retention policy version."""

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
    """Append-only preservation instruction for one claim."""

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


class LegalHoldProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-self-authorizing preservation proposal from an automated signal.

    Source identity and payload are represented by hashes/fingerprints rather
    than raw transport payloads. A proposal can move once from pending to either
    activated or rejected. Activation links the exact formal ClaimLegalHold.
    """

    __tablename__ = "legal_hold_proposals"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "source_kind",
            "source_ref_fingerprint",
            name="uq_legal_hold_proposal_signal_identity",
        ),
        CheckConstraint(
            "status IN ('pending', 'activated', 'rejected')",
            name="ck_legal_hold_proposal_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND hold_id IS NULL AND decided_at IS NULL AND decided_by_id IS NULL AND decision_reason IS NULL) OR "
            "(status = 'activated' AND hold_id IS NOT NULL AND decided_at IS NOT NULL AND decided_by_id IS NOT NULL AND decision_reason IS NOT NULL) OR "
            "(status = 'rejected' AND hold_id IS NULL AND decided_at IS NOT NULL AND decided_by_id IS NOT NULL AND decision_reason IS NOT NULL)",
            name="ck_legal_hold_proposal_lifecycle",
        ),
        Index(
            "ix_legal_hold_proposals_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    recommended_hold_source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    hold_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claim_legal_holds.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
