from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryCutoverExecutionLease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Short-lived non-routable execution lease for a governed reversible recovery cutover."""

    __tablename__ = "evidence_recovery_cutover_execution_leases"
    __table_args__ = (
        CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_cutover_exec_status"),
        CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_cutover_exec_four_eyes"),
        CheckConstraint("admission_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_cutover_exec_approver_split"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_cutover_exec_no_read_switch"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_cutover_exec_no_key_mut"),
        CheckConstraint("active_backend_changed = false", name="ck_recovery_cutover_exec_no_backend"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_cutover_exec_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_cutover_exec_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_cutover_exec_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_cutover_exec_no_local_del"),
        UniqueConstraint("cutover_admission_id", name="uq_recovery_cutover_exec_admission"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_recovery_cutover_exec_org_hash"),
        Index("ix_recovery_cutover_exec_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_recovery_cutover_exec_org_doc_status", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    cutover_admission_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_admissions.id", ondelete="RESTRICT"), nullable=False, index=True)
    admission_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_admission_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    authority_switch_rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_authority_switch_rehearsals.id", ondelete="RESTRICT"), nullable=False, index=True)
    shadow_promotion_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_shadow_promotions.id", ondelete="RESTRICT"), nullable=False, index=True)
    attestation_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_promotion_attestations.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)
    restore_rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_restore_rehearsals.id", ondelete="RESTRICT"), nullable=False, index=True)
    restore_verification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_restore_verifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    shadow_verification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_shadow_verifications.id", ondelete="RESTRICT"), nullable=False, index=True)

    admission_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    transition_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rehearsal_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rehearsal_lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared", server_default="prepared")
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admission_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    prepared_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    preparation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    activated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rolled_back_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    active_backend_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryCutoverExecutionReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only transition receipt for a non-routable cutover execution lease."""

    __tablename__ = "evidence_recovery_cutover_execution_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_cutover_exec_receipt_phase"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_cutover_exec_rec_no_read"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_cutover_exec_rec_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_cutover_exec_rec_no_dest"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_cutover_exec_rec_org_hash"),
        Index("ix_recovery_cutover_exec_receipt_time", "execution_lease_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_execution_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    cutover_admission_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_admissions.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_state: Mapped[str] = mapped_column(String(20), nullable=False)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    admission_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
