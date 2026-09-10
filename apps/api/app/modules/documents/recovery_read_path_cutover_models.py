from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryReadPathCutoverAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Governed approval evidence for a future reversible routable read-path cutover."""

    __tablename__ = "evidence_recovery_read_path_cutover_authorizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_recovery_read_cut_auth_status",
        ),
        CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_recovery_read_cut_auth_four_eyes",
        ),
        CheckConstraint(
            "execution_activated_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_recovery_read_cut_auth_activator_split",
        ),
        CheckConstraint("routable_authority_created = false", name="ck_recovery_read_cut_auth_no_route_auth"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_read_cut_auth_no_read_switch"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_cut_auth_no_key_mut"),
        CheckConstraint("active_backend_changed = false", name="ck_recovery_read_cut_auth_no_backend"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_cut_auth_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_cut_auth_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_read_cut_auth_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_read_cut_auth_no_local_del"),
        UniqueConstraint("execution_lease_id", name="uq_recovery_read_cut_auth_lease"),
        UniqueConstraint("organization_id", "authorization_hash", name="uq_recovery_read_cut_auth_org_hash"),
        Index("ix_recovery_read_cut_auth_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_recovery_read_cut_auth_org_doc_status", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_execution_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_execution_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_rollback_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_execution_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    cutover_admission_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_admissions.id", ondelete="RESTRICT"), nullable=False, index=True)
    admission_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_admission_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    authority_switch_rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_authority_switch_rehearsals.id", ondelete="RESTRICT"), nullable=False, index=True)
    shadow_promotion_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_shadow_promotions.id", ondelete="RESTRICT"), nullable=False, index=True)
    attestation_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_promotion_attestations.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)
    restore_rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_restore_rehearsals.id", ondelete="RESTRICT"), nullable=False, index=True)
    restore_verification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_restore_verifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    shadow_verification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_shadow_verifications.id", ondelete="RESTRICT"), nullable=False, index=True)

    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_rollback_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_transition_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rehearsal_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rehearsal_lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")
    authorization_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    active_backend_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryReadPathCutoverAuthorizationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only governance receipt for production read-path cutover authorization."""

    __tablename__ = "evidence_recovery_read_path_cutover_authorization_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('requested', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_recovery_read_cut_auth_receipt_phase",
        ),
        CheckConstraint("routable_authority_created = false", name="ck_recovery_read_cut_auth_rec_no_route"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_read_cut_auth_rec_no_read"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_cut_auth_rec_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_cut_auth_rec_no_dest"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_read_cut_auth_rec_org_hash"),
        Index("ix_recovery_read_cut_auth_receipt_time", "authorization_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_cutover_execution_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_transition_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
