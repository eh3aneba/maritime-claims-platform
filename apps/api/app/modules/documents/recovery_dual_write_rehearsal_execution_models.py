from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryDualWriteRehearsalExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Phase Y evidence for one bounded non-routable recovery write rehearsal."""

    __tablename__ = "evidence_recovery_dual_write_rehearsal_executions"
    __table_args__ = (
        CheckConstraint("status = 'executed'", name="ck_dw_reh_exec_status"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_reh_exec_size"),
        CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_reh_exec_obs_size"),
        CheckConstraint("max_rehearsal_writes = 1", name="ck_dw_reh_exec_one_write"),
        CheckConstraint("route_version_at_execution >= 1", name="ck_dw_reh_exec_routever"),
        CheckConstraint("rehearsal_executed = true", name="ck_dw_reh_exec_exec"),
        CheckConstraint("rehearsal_write_verified = true", name="ck_dw_reh_exec_verified"),
        CheckConstraint("rehearsal_object_routable = false", name="ck_dw_reh_exec_nonroute"),
        CheckConstraint("dual_write_active = false", name="ck_dw_reh_exec_no_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_exec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_dw_reh_exec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_reh_exec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_exec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_exec_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_exec_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_exec_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_exec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_reh_exec_no_localdel"),
        UniqueConstraint("phase_x_authorization_id", name="uq_dw_reh_exec_x_auth"),
        UniqueConstraint("phase_x_approval_receipt_id", name="uq_dw_reh_exec_x_receipt"),
        UniqueConstraint("organization_id", "execution_hash", name="uq_dw_reh_exec_org_hash"),
        Index("ix_dw_reh_exec_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_reh_exec_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_auth_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_w_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_owner_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_v_transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_u_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    phase_x_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_x_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_w_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    route_version_at_execution: Mapped[int] = mapped_column(Integer, nullable=False)
    rehearsal_object_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    max_rehearsal_writes: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    conditional_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="executed", server_default="executed")
    executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_reason: Mapped[str] = mapped_column(Text, nullable=False)

    rehearsal_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    rehearsal_write_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    rehearsal_object_routable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


class EvidenceRecoveryDualWriteRehearsalExecutionReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only receipt for a completed Phase Y rehearsal."""

    __tablename__ = "evidence_recovery_dual_write_rehearsal_execution_receipts"
    __table_args__ = (
        CheckConstraint("phase = 'executed'", name="ck_dw_reh_exec_rec_phase"),
        CheckConstraint("rehearsal_executed = true", name="ck_dw_reh_exec_rec_exec"),
        CheckConstraint("rehearsal_write_verified = true", name="ck_dw_reh_exec_rec_verified"),
        CheckConstraint("rehearsal_object_routable = false", name="ck_dw_reh_exec_rec_nonroute"),
        CheckConstraint("dual_write_active = false", name="ck_dw_reh_exec_rec_no_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_exec_rec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_dw_reh_exec_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_reh_exec_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_exec_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_exec_rec_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_exec_rec_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_exec_rec_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_exec_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_reh_exec_rec_no_localdel"),
        UniqueConstraint("execution_id", name="uq_dw_reh_exec_rec_execution"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_reh_exec_rec_org_hash"),
        Index("ix_dw_reh_exec_rec_time", "execution_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="executed", server_default="executed")
    phase_x_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_x_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rehearsal_object_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conditional_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rehearsal_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    rehearsal_write_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    rehearsal_object_routable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
