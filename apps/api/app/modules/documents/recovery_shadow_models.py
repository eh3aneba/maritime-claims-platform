from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryShadowPromotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable proof that an approved recovery candidate was materialized only in shadow storage."""

    __tablename__ = "evidence_recovery_shadow_promotions"
    __table_args__ = (
        UniqueConstraint("attestation_id", name="uq_evidence_recovery_shadow_promotion_attestation"),
        UniqueConstraint(
            "organization_id",
            "shadow_promotion_hash",
            name="uq_evidence_recovery_shadow_promotion_org_hash",
        ),
        Index(
            "ix_evidence_recovery_shadow_promotions_org_claim",
            "organization_id",
            "claim_id",
        ),
        CheckConstraint(
            "source_file_size_bytes >= 0",
            name="ck_evidence_recovery_shadow_promotion_source_size",
        ),
        CheckConstraint(
            "shadow_file_size_bytes >= 0",
            name="ck_evidence_recovery_shadow_promotion_shadow_size",
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
    attestation_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_promotion_attestations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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

    attestation_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    promotion_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
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

    shadow_storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    shadow_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shadow_promotion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    rehearsal_reason: Mapped[str] = mapped_column(Text, nullable=False)
    promoted_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecoveryShadowVerification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only integrity proof for an existing shadow promotion rehearsal."""

    __tablename__ = "evidence_recovery_shadow_verifications"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "verification_hash",
            name="uq_evidence_recovery_shadow_verification_org_hash",
        ),
        Index(
            "ix_evidence_recovery_shadow_verifications_rehearsal_time",
            "shadow_promotion_id",
            "verified_at",
        ),
        CheckConstraint(
            "expected_file_size_bytes >= 0",
            name="ck_evidence_recovery_shadow_verification_expected_size",
        ),
        CheckConstraint(
            "shadow_file_size_bytes >= 0",
            name="ck_evidence_recovery_shadow_verification_shadow_size",
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
    attestation_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_promotion_attestations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shadow_promotion_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_shadow_promotions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    expected_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shadow_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promotion_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_reason: Mapped[str] = mapped_column(Text, nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
