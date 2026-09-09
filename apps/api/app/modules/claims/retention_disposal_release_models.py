from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DisposalReleaseReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Final human release review for a live logical quarantine stage.

    This record is governance evidence only. Even when approved it creates no
    execution credential, deletion authority, or physical disposal command.
    """

    __tablename__ = "disposal_release_reviews"
    __table_args__ = (
        UniqueConstraint(
            "disposal_quarantine_stage_id",
            name="uq_disposal_release_review_stage",
        ),
        UniqueConstraint(
            "organization_id",
            "review_hash",
            name="uq_disposal_release_review_org_hash",
        ),
        CheckConstraint(
            "status IN ('pending_final_approval', 'approved', 'rejected', 'invalidated', 'expired', 'cancelled')",
            name="ck_disposal_release_review_status",
        ),
        CheckConstraint(
            "(status = 'pending_final_approval' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'approved' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('rejected', 'invalidated', 'expired', 'cancelled') "
            "AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL "
            "AND approval_hash IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL "
            "AND terminal_reason IS NOT NULL)",
            name="ck_disposal_release_review_lifecycle",
        ),
        CheckConstraint(
            "approved_by_id IS NULL OR approved_by_id <> requested_by_id",
            name="ck_disposal_release_review_distinct_requester_approver",
        ),
        CheckConstraint(
            "approved_by_id IS NULL OR approved_by_id <> quarantine_staged_by_id",
            name="ck_disposal_release_review_distinct_stage_creator_approver",
        ),
        CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_release_review_document_count",
        ),
        CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_release_review_total_bytes",
        ),
        CheckConstraint(
            "minimum_release_eligible_at >= quarantine_staged_at",
            name="ck_disposal_release_review_minimum_dwell",
        ),
        CheckConstraint(
            "review_expires_at <= quarantine_stage_expires_at",
            name="ck_disposal_release_review_expiry_bound",
        ),
        Index(
            "ix_disposal_release_reviews_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_disposal_release_reviews_org_expiry",
            "organization_id",
            "review_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    disposal_quarantine_stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_quarantine_stages.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    disposal_dry_run_ceremony_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_dry_run_ceremonies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    disposal_execution_manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_execution_manifests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    disposal_authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_authorizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    retention_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_retention_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    inventory_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ceremony_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attestation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    overlay_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    release_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    release_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    quarantine_staged_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quarantine_staged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quarantine_stage_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minimum_release_eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_revalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_final_approval",
        server_default="pending_final_approval",
    )

    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
