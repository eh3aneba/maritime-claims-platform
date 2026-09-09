from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryRestoreRehearsal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable proof that a verified recovery replica was restored into isolated staging."""

    __tablename__ = "evidence_recovery_restore_rehearsals"
    __table_args__ = (
        UniqueConstraint("replica_id", name="uq_evidence_recovery_restore_rehearsal_replica"),
        UniqueConstraint(
            "organization_id",
            "rehearsal_hash",
            name="uq_evidence_recovery_restore_rehearsal_org_hash",
        ),
        Index(
            "ix_evidence_recovery_restore_rehearsals_org_claim",
            "organization_id",
            "claim_id",
        ),
        CheckConstraint(
            "source_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_rehearsal_source_size",
        ),
        CheckConstraint(
            "restored_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_rehearsal_restored_size",
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
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_document_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    staging_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    restored_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    restored_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rehearsal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    restored_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    restored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecoveryRestoreVerification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only proof that remote and staged restore bytes remain hash-correct."""

    __tablename__ = "evidence_recovery_restore_verifications"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "verification_hash",
            name="uq_evidence_recovery_restore_verification_org_hash",
        ),
        Index(
            "ix_evidence_recovery_restore_verifications_org_claim",
            "organization_id",
            "claim_id",
        ),
        Index(
            "ix_evidence_recovery_restore_verifications_rehearsal_time",
            "rehearsal_id",
            "verified_at",
        ),
        CheckConstraint(
            "expected_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_verification_expected_size",
        ),
        CheckConstraint(
            "remote_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_verification_remote_size",
        ),
        CheckConstraint(
            "staged_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_verification_staged_size",
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
        ForeignKey("evidence_recovery_restore_rehearsals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    expected_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    staged_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    staged_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_reason: Mapped[str] = mapped_column(Text, nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
