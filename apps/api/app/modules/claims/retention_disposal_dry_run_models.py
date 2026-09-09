from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DisposalDryRunCeremony(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Human-attested, non-destructive rehearsal of a disposal manifest.

    The ceremony records a simulated plan derived from hashed manifest metadata.
    It never carries executable credentials or permission to mutate/delete data.
    """

    __tablename__ = "disposal_dry_run_ceremonies"
    __table_args__ = (
        UniqueConstraint(
            "disposal_execution_manifest_id",
            name="uq_disposal_dry_run_ceremony_manifest",
        ),
        UniqueConstraint(
            "organization_id",
            "ceremony_hash",
            name="uq_disposal_dry_run_ceremony_org_hash",
        ),
        CheckConstraint(
            "status IN ('pending_attestation', 'attested', 'blocked', 'invalidated', 'expired', 'cancelled')",
            name="ck_disposal_dry_run_ceremony_status",
        ),
        CheckConstraint(
            "(status = 'pending_attestation' AND attested_by_id IS NULL AND attested_at IS NULL "
            "AND attestation_hash IS NULL AND attestation_reason IS NULL "
            "AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'attested' AND attested_by_id IS NOT NULL AND attested_at IS NOT NULL "
            "AND attestation_hash IS NOT NULL AND attestation_reason IS NOT NULL "
            "AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('blocked', 'invalidated', 'expired', 'cancelled') "
            "AND attested_by_id IS NULL AND attested_at IS NULL AND attestation_hash IS NULL "
            "AND attestation_reason IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_disposal_dry_run_ceremony_lifecycle",
        ),
        CheckConstraint(
            "attested_by_id IS NULL OR attested_by_id <> created_by_id",
            name="ck_disposal_dry_run_ceremony_distinct_attester",
        ),
        CheckConstraint(
            "document_count >= 0",
            name="ck_disposal_dry_run_ceremony_document_count",
        ),
        CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_disposal_dry_run_ceremony_total_bytes",
        ),
        CheckConstraint(
            "ceremony_expires_at <= manifest_expires_at",
            name="ck_disposal_dry_run_ceremony_expiry_bound",
        ),
        Index(
            "ix_disposal_dry_run_ceremonies_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_disposal_dry_run_ceremonies_org_expiry",
            "organization_id",
            "ceremony_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
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
    retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    dry_run_plan: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ceremony_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    opening_reason: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ceremony_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_revalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_attestation",
        server_default="pending_attestation",
    )
    attested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attestation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attestation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
