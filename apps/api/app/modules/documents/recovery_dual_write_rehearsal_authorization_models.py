from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryDualWriteRehearsalAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Phase X governance authorization for one later bounded dual-write rehearsal."""

    __tablename__ = "evidence_recovery_dual_write_rehearsal_authorizations"
    __table_args__ = (
        CheckConstraint("status IN ('pending_second_approval','approved','rejected','expired','invalidated')", name="ck_dw_reh_auth_status"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_reh_auth_healthy"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_four_eyes"),
        CheckConstraint("phase_w_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_w_split"),
        CheckConstraint("phase_v_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_v_split"),
        CheckConstraint("phase_u_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_u_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_reh_auth_size"),
        CheckConstraint("verified_read_count >= 1", name="ck_dw_reh_auth_verified"),
        CheckConstraint("integrity_failure_count = 0", name="ck_dw_reh_auth_integrity"),
        CheckConstraint("storage_unavailable_count = 0", name="ck_dw_reh_auth_storage"),
        CheckConstraint("route_version_at_request >= 1", name="ck_dw_reh_auth_routever"),
        CheckConstraint("max_rehearsal_writes = 1", name="ck_dw_reh_auth_one_write"),
        CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_dw_reh_auth_approved_exp"),
        CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_dw_reh_auth_nonapproved_exp"),
        CheckConstraint("rehearsal_executed = false", name="ck_dw_reh_auth_no_exec"),
        CheckConstraint("dual_write_active = false", name="ck_dw_reh_auth_no_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_auth_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_dw_reh_auth_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_reh_auth_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_auth_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_auth_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_auth_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_auth_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_auth_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_reh_auth_no_localdel"),
        UniqueConstraint("phase_w_health_qualification_id", name="uq_dw_reh_auth_w_health"),
        UniqueConstraint("organization_id", "authorization_hash", name="uq_dw_reh_auth_org_hash"),
        Index("ix_dw_reh_auth_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_reh_auth_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_w_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_owner_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_w_health_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_owner_health_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_v_transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_u_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    phase_w_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_w_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_w_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    phase_v_transition_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_u_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_t_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    route_expired_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    operational_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    max_rehearsal_writes: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    phase_w_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_v_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_u_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rehearsal_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only Phase X authorization receipt."""

    __tablename__ = "evidence_recovery_dual_write_rehearsal_auth_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','approved','rejected','expired','invalidated')", name="ck_dw_reh_rec_phase"),
        CheckConstraint("rehearsal_executed = false", name="ck_dw_reh_rec_no_exec"),
        CheckConstraint("dual_write_active = false", name="ck_dw_reh_rec_no_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_rec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_dw_reh_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_reh_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_rec_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_rec_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_rec_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_reh_rec_no_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_reh_rec_org_hash"),
        Index("ix_dw_reh_rec_time", "authorization_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_w_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_owner_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rehearsal_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
