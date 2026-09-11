from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryRoutableDualWriteCanaryAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Phase AA governance authorization for one later bounded routable dual-write canary."""

    __tablename__ = "evidence_recovery_routable_dual_write_canary_authorizations"
    __table_args__ = (
        CheckConstraint("status IN ('pending_second_approval','approved','rejected','expired','invalidated')", name="ck_dw_can_auth_status"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_can_auth_healthy"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_can_auth_four_eyes"),
        CheckConstraint("phase_z_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_can_auth_z_split"),
        CheckConstraint("phase_y_executed_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_can_auth_y_split"),
        CheckConstraint("phase_x_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_can_auth_x_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_can_auth_size"),
        CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_can_auth_obs_size"),
        CheckConstraint("route_version_at_request >= 1", name="ck_dw_can_auth_routever"),
        CheckConstraint("max_canary_windows = 1", name="ck_dw_can_auth_one_window"),
        CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_dw_can_auth_approved_exp"),
        CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_dw_can_auth_nonapproved_exp"),
        CheckConstraint("storage_write_performed = false", name="ck_dw_can_auth_no_store_write"),
        CheckConstraint("canary_executed = false", name="ck_dw_can_auth_no_exec"),
        CheckConstraint("routable_dual_write_active = false", name="ck_dw_can_auth_no_routable_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_can_auth_no_durable"),
        CheckConstraint("rehearsal_object_routable = false", name="ck_dw_can_auth_reh_nonroute"),
        CheckConstraint("read_path_switched = false", name="ck_dw_can_auth_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_can_auth_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_can_auth_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_can_auth_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_can_auth_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_can_auth_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_can_auth_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_can_auth_no_localdel"),
        UniqueConstraint("phase_z_health_qualification_id", name="uq_dw_can_auth_z_health"),
        UniqueConstraint("organization_id", "authorization_hash", name="uq_dw_can_auth_org_hash"),
        Index("ix_dw_can_auth_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_can_auth_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_z_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_z_health_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_health_receipts.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    phase_z_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_z_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_z_integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_z_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    rehearsal_object_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    max_canary_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    phase_z_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_y_executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")
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

    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    canary_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    routable_dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    rehearsal_object_routable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_recovery_routable_dual_write_canary_auth_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','approved','rejected','expired','invalidated')", name="ck_dw_can_rec_phase"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_can_rec_healthy"),
        CheckConstraint("storage_write_performed = false", name="ck_dw_can_rec_no_store_write"),
        CheckConstraint("canary_executed = false", name="ck_dw_can_rec_no_exec"),
        CheckConstraint("routable_dual_write_active = false", name="ck_dw_can_rec_no_routable_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_can_rec_no_durable"),
        CheckConstraint("rehearsal_object_routable = false", name="ck_dw_can_rec_reh_nonroute"),
        CheckConstraint("read_path_switched = false", name="ck_dw_can_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_can_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_can_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_can_rec_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_can_rec_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_can_rec_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_can_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_can_rec_no_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_can_rec_org_hash"),
        Index("ix_dw_can_rec_time", "authorization_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_z_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    phase_z_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_z_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    canary_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    routable_dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    rehearsal_object_routable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
