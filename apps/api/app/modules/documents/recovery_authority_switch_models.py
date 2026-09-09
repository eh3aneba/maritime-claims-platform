from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryAuthoritySwitchRehearsal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Virtual, reversible authority-switch rehearsal with no production cutover effect."""

    __tablename__ = "evidence_recovery_authority_switch_rehearsals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')",
            name="ck_evidence_recovery_authority_switch_status",
        ),
        CheckConstraint(
            "virtual_authority_class IN ('authoritative_source', 'recovery_shadow_candidate')",
            name="ck_evidence_recovery_authority_switch_virtual_class",
        ),
        CheckConstraint(
            "prepared_by_id <> activated_by_id OR activated_by_id IS NULL",
            name="ck_evidence_recovery_authority_switch_four_eyes",
        ),
        CheckConstraint(
            "cutover_performed = false",
            name="ck_evidence_recovery_authority_switch_no_cutover",
        ),
        CheckConstraint(
            "authoritative_storage_changed = false",
            name="ck_evidence_recovery_authority_switch_no_authority_change",
        ),
        CheckConstraint(
            "document_storage_key_mutated = false",
            name="ck_evidence_recovery_authority_switch_no_key_mutation",
        ),
        CheckConstraint(
            "active_backend_changed = false",
            name="ck_evidence_recovery_authority_switch_no_backend_change",
        ),
        UniqueConstraint(
            "shadow_promotion_id",
            name="uq_evidence_recovery_authority_switch_shadow",
        ),
        UniqueConstraint(
            "organization_id",
            "contract_hash",
            name="uq_evidence_recovery_authority_switch_org_contract",
        ),
        Index(
            "ix_evidence_recovery_authority_switch_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_evidence_recovery_authority_switch_org_document_status",
            "organization_id",
            "document_id",
            "status",
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
    shadow_promotion_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_shadow_promotions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attestation_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_promotion_attestations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    replica_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    restore_rehearsal_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_restore_rehearsals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    restore_verification_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_restore_verifications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shadow_verification_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_shadow_verifications.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    attestation_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    promotion_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_promotion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared", server_default="prepared")
    virtual_authority_class: Mapped[str] = mapped_column(
        String(40), nullable=False, default="authoritative_source", server_default="authoritative_source"
    )
    virtual_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    prepared_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    preparation_reason: Mapped[str] = mapped_column(Text, nullable=False)

    activated_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rolled_back_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    cutover_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    active_backend_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryAuthoritySwitchReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only receipt for one virtual authority-switch transition."""

    __tablename__ = "evidence_recovery_authority_switch_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')",
            name="ck_evidence_recovery_authority_switch_receipt_phase",
        ),
        CheckConstraint(
            "cutover_performed = false",
            name="ck_evidence_recovery_authority_switch_receipt_no_cutover",
        ),
        CheckConstraint(
            "authoritative_storage_changed = false",
            name="ck_evidence_recovery_authority_switch_receipt_no_authority_change",
        ),
        UniqueConstraint(
            "organization_id",
            "receipt_hash",
            name="uq_evidence_recovery_authority_switch_receipt_org_hash",
        ),
        Index(
            "ix_evidence_recovery_authority_switch_receipt_rehearsal_time",
            "authority_switch_rehearsal_id",
            "transitioned_at",
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
    authority_switch_rehearsal_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_authority_switch_rehearsals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    shadow_promotion_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_shadow_promotions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    from_authority_class: Mapped[str] = mapped_column(String(40), nullable=False)
    to_authority_class: Mapped[str] = mapped_column(String(40), nullable=False)
    from_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    to_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutover_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
