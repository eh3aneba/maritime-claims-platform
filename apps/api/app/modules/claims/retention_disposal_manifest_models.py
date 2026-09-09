from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DisposalExecutionManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable preflight inventory plus bounded lifecycle metadata.

    The inventory contains identifiers, hashes, and storage-key fingerprints
    only. It is not an execution command and never mutates claim/evidence data.
    """

    __tablename__ = "disposal_execution_manifests"
    __table_args__ = (
        UniqueConstraint(
            "disposal_authorization_id",
            name="uq_disposal_execution_manifest_authorization",
        ),
        UniqueConstraint(
            "organization_id",
            "manifest_hash",
            name="uq_disposal_execution_manifest_org_hash",
        ),
        CheckConstraint(
            "status IN ('ready', 'blocked', 'invalidated', 'expired')",
            name="ck_disposal_execution_manifest_status",
        ),
        CheckConstraint(
            "(status = 'ready' AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('blocked', 'invalidated', 'expired') AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_disposal_execution_manifest_lifecycle",
        ),
        CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_execution_manifest_document_count",
        ),
        CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_execution_manifest_total_bytes",
        ),
        CheckConstraint(
            "manifest_expires_at <= authorization_expires_at",
            name="ck_disposal_execution_manifest_expiry_bound",
        ),
        Index(
            "ix_disposal_execution_manifests_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_disposal_execution_manifests_org_expiry",
            "organization_id",
            "manifest_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
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
    retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    inventory: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    inventory_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_hold_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pending_proposal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    manifest_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_revalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="ready", server_default="ready"
    )
    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
