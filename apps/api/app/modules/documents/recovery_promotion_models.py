from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryPromotionAttestation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Four-eyes, non-cutover attestation for a future recovery promotion.

    Approval proves that an exact recovery replica + restore rehearsal lineage was
    reviewed in its current state. It never changes document storage authority.
    """

    __tablename__ = "evidence_recovery_promotion_attestations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_evidence_recovery_promotion_attestation_status",
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
            name="ck_evidence_recovery_promotion_attestation_lifecycle",
        ),
        CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_evidence_recovery_promotion_attestation_four_eyes",
        ),
        CheckConstraint(
            "cutover_performed = false",
            name="ck_evidence_recovery_promotion_no_cutover",
        ),
        CheckConstraint(
            "authoritative_storage_changed = false",
            name="ck_evidence_recovery_promotion_no_authority_change",
        ),
        UniqueConstraint(
            "organization_id",
            "request_snapshot_hash",
            name="uq_evidence_recovery_promotion_org_snapshot",
        ),
        Index(
            "ix_evidence_recovery_promotion_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_evidence_recovery_promotion_org_document_status",
            "organization_id",
            "document_id",
            "status",
        ),
        Index(
            "ix_evidence_recovery_promotion_org_status_expiry",
            "organization_id",
            "status",
            "attestation_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    replica_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rehearsal_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_restore_rehearsals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    restore_verification_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_restore_verifications.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rehearsal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    restore_verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_document_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    promotion_plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    promotion_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attestation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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

    cutover_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    authoritative_storage_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
