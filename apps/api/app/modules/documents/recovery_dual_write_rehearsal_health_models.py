from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryDualWriteRehearsalHealthQualification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Phase Z independent non-routable health qualification for one Phase Y execution."""

    __tablename__ = "evidence_recovery_dual_write_rehearsal_health_qualifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending_second_approval','qualified','rejected','expired','invalidated')", name="ck_dw_reh_health_status"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_reh_health_healthy"),
        CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_reh_health_four_eyes"),
        CheckConstraint("phase_y_executed_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_reh_health_y_split"),
        CheckConstraint("phase_x_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_reh_health_x_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_reh_health_size"),
        CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_reh_health_obs_size"),
        CheckConstraint("route_version_at_request >= 1", name="ck_dw_reh_health_routever"),
        CheckConstraint("storage_write_performed = false", name="ck_dw_reh_health_no_storage_write"),
        CheckConstraint("routable_dual_write_authority_created = false", name="ck_dw_reh_health_no_route_auth"),
        CheckConstraint("rehearsal_object_routable = false", name="ck_dw_reh_health_nonroute"),
        CheckConstraint("dual_write_active = false", name="ck_dw_reh_health_no_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_health_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_dw_reh_health_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_reh_health_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_health_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_health_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_health_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_health_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_health_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_reh_health_no_localdel"),
        UniqueConstraint("execution_id", name="uq_dw_reh_health_execution"),
        UniqueConstraint("organization_id", "health_qualification_hash", name="uq_dw_reh_health_org_hash"),
        Index("ix_dw_reh_health_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_reh_health_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_execution_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_x_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_auth_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_w_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_owner_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_v_transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_u_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

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
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")

    phase_y_executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_x_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")
    qualified_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    qualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    routable_dual_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


class EvidenceRecoveryDualWriteRehearsalHealthReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_recovery_dual_write_rehearsal_health_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','qualified','rejected','expired','invalidated')", name="ck_dw_reh_health_rec_phase"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_reh_health_rec_healthy"),
        CheckConstraint("storage_write_performed = false", name="ck_dw_reh_health_rec_no_storage_write"),
        CheckConstraint("routable_dual_write_authority_created = false", name="ck_dw_reh_health_rec_no_route_auth"),
        CheckConstraint("rehearsal_object_routable = false", name="ck_dw_reh_health_rec_nonroute"),
        CheckConstraint("dual_write_active = false", name="ck_dw_reh_health_rec_no_dual"),
        CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_health_rec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_dw_reh_health_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_dw_reh_health_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_health_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_health_rec_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_health_rec_no_dest"),
        CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_health_rec_no_copy"),
        CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_health_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_dw_reh_health_rec_no_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_reh_health_rec_org_hash"),
        Index("ix_dw_reh_health_rec_time", "health_qualification_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    routable_dual_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
