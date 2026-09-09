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


class DisposalQuarantineStage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reversible logical quarantine overlay for an attested disposal dry run.

    The record is governance metadata only. It never moves, deletes, archives,
    tombstones, rewrites, or otherwise mutates claim/evidence/storage content.
    """

    __tablename__ = "disposal_quarantine_stages"
    __table_args__ = (
        UniqueConstraint(
            "disposal_dry_run_ceremony_id",
            name="uq_disposal_quarantine_stage_ceremony",
        ),
        UniqueConstraint(
            "organization_id",
            "stage_hash",
            name="uq_disposal_quarantine_stage_org_hash",
        ),
        CheckConstraint(
            "status IN ('staged', 'restored', 'invalidated', 'expired', 'cancelled')",
            name="ck_disposal_quarantine_stage_status",
        ),
        CheckConstraint(
            "(status = 'staged' AND restored_by_id IS NULL AND restored_at IS NULL "
            "AND restoration_reason IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'restored' AND restored_by_id IS NOT NULL AND restored_at IS NOT NULL "
            "AND restoration_reason IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('invalidated', 'expired', 'cancelled') "
            "AND restored_by_id IS NULL AND restored_at IS NULL "
            "AND restoration_reason IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_disposal_quarantine_stage_lifecycle",
        ),
        CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_quarantine_stage_document_count",
        ),
        CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_quarantine_stage_total_bytes",
        ),
        CheckConstraint(
            "stage_expires_at <= ceremony_expires_at",
            name="ck_disposal_quarantine_stage_expiry_bound",
        ),
        Index(
            "ix_disposal_quarantine_stages_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_disposal_quarantine_stages_org_expiry",
            "organization_id",
            "stage_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
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
    retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ceremony_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    overlay_plan: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    overlay_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    staged_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    staging_reason: Mapped[str] = mapped_column(Text, nullable=False)
    staged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_revalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="staged", server_default="staged"
    )

    restored_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    restored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restoration_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
