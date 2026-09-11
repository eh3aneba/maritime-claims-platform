from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SafetyMixin:
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    canary_reactivated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    routable_dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_put_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("canary_reactivated = false", name=f"ck_{prefix}_no_reactivate"),
        CheckConstraint("routable_dual_write_active = false", name=f"ck_{prefix}_no_active"),
        CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_switch"),
        CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    )


class EvidenceRecoveryRoutableDualWriteCanaryHealthQualification(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    __tablename__ = "evidence_recovery_routable_dual_write_canary_health_qualifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending_second_approval','qualified','rejected','expired','invalidated')", name="ck_dw_can_health_status"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_can_health_healthy"),
        CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_four_eyes"),
        CheckConstraint("phase_ab_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_ab_split"),
        CheckConstraint("phase_aa_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_aar_split"),
        CheckConstraint("phase_aa_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_aaa_split"),
        CheckConstraint("phase_z_qualified_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_z_split"),
        CheckConstraint("phase_y_executed_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_y_split"),
        CheckConstraint("phase_x_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_x_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_can_health_size"),
        CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_can_health_obs_size"),
        CheckConstraint("read_route_version_at_request >= 1", name="ck_dw_can_health_read_ver"),
        CheckConstraint("write_route_version_at_request >= 1", name="ck_dw_can_health_write_ver"),
        UniqueConstraint("canary_lease_id", name="uq_dw_can_health_lease"),
        UniqueConstraint("organization_id", "health_qualification_hash", name="uq_dw_can_health_org_hash"),
        Index("ix_dw_can_health_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_can_health_org_doc", "organization_id", "document_id", "status"),
        *_safety_constraints("dw_can_health"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    canary_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_auth_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_z_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_health_qualifications.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_executions.id", ondelete="RESTRICT"), nullable=False)
    phase_x_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False)
    activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_receipts.id", ondelete="RESTRICT"), nullable=False)
    terminal_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_receipts.id", ondelete="RESTRICT"), nullable=False)

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_z_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_x_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    canary_object_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    write_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")

    phase_ab_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_aa_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_aa_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_z_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
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


class EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    __tablename__ = "evidence_recovery_routable_dual_write_canary_health_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','qualified','rejected','expired','invalidated')", name="ck_dw_can_health_rec_phase"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_can_health_rec_healthy"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_can_health_rec_org_hash"),
        Index("ix_dw_can_health_rec_time", "health_qualification_id", "transitioned_at"),
        *_safety_constraints("dw_can_health_rec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    canary_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
