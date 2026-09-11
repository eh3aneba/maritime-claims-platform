from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SafetyMixin:
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
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


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        CheckConstraint("rehearsal_object_routable = false", name=f"ck_{prefix}_reh_nonroute"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write_switch"),
        CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    )


class EvidenceRecoveryRoutableDualWriteCanaryLease(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    """One bounded Phase AB canary window; local remains authoritative throughout."""

    __tablename__ = "evidence_recovery_routable_dual_write_canary_leases"
    __table_args__ = (
        CheckConstraint("status IN ('active','rolled_back','expired','invalidated')", name="ck_dw_can_lease_status"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_can_lease_size"),
        CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_can_lease_obs_size"),
        CheckConstraint("read_route_version_at_activation >= 1", name="ck_dw_can_lease_read_ver"),
        CheckConstraint("write_route_version_at_activation >= 1", name="ck_dw_can_lease_write_ver"),
        CheckConstraint("max_canary_writes = 1", name="ck_dw_can_lease_one_write"),
        CheckConstraint("canary_executed = true", name="ck_dw_can_lease_exec"),
        CheckConstraint("canary_write_verified = true", name="ck_dw_can_lease_verified"),
        CheckConstraint("((status = 'active' AND routable_dual_write_active = true) OR (status <> 'active' AND routable_dual_write_active = false))", name="ck_dw_can_lease_active_flag"),
        *_safety_constraints("dw_can_lease"),
        UniqueConstraint("authorization_id", name="uq_dw_can_lease_auth"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_dw_can_lease_org_hash"),
        Index("ix_dw_can_lease_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_can_lease_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_auth_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_z_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_health_qualifications.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_executions.id", ondelete="RESTRICT"), nullable=False)
    phase_x_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_dual_write_rehearsal_authorizations.id", ondelete="RESTRICT"), nullable=False)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False)

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_z_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_x_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    read_route_version_at_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    write_route_version_at_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    canary_object_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    max_canary_writes: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    canary_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    canary_write_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    routable_dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceRecoveryRoutableDualWriteCanaryRoute(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    """Dedicated write-routing control plane; independent from the existing read route."""

    __tablename__ = "evidence_recovery_routable_dual_write_canary_routes"
    __table_args__ = (
        CheckConstraint("write_mode IN ('local_only','local_plus_recovery_canary')", name="ck_dw_can_route_mode"),
        CheckConstraint("route_version >= 1", name="ck_dw_can_route_version"),
        CheckConstraint("((write_mode = 'local_only' AND active_canary_lease_id IS NULL) OR (write_mode = 'local_plus_recovery_canary' AND active_canary_lease_id IS NOT NULL))", name="ck_dw_can_route_binding"),
        *_safety_constraints("dw_can_route"),
        UniqueConstraint("document_id", name="uq_dw_can_route_document"),
        Index("ix_dw_can_route_org_claim", "organization_id", "claim_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    write_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="local_only", server_default="local_only")
    active_canary_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    changed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecoveryRoutableDualWriteCanaryReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    __tablename__ = "evidence_recovery_routable_dual_write_canary_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('activated','rolled_back','expired','invalidated')", name="ck_dw_can_exec_rec_phase"),
        CheckConstraint("from_write_mode IN ('local_only','local_plus_recovery_canary') AND to_write_mode IN ('local_only','local_plus_recovery_canary')", name="ck_dw_can_exec_rec_modes"),
        CheckConstraint("canary_executed = true", name="ck_dw_can_exec_rec_exec"),
        CheckConstraint("canary_write_verified = true", name="ck_dw_can_exec_rec_verified"),
        CheckConstraint("((phase = 'activated' AND routable_dual_write_active = true) OR (phase <> 'activated' AND routable_dual_write_active = false))", name="ck_dw_can_exec_rec_active"),
        *_safety_constraints("dw_can_exec_rec"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_can_exec_rec_org_hash"),
        Index("ix_dw_can_exec_rec_time", "canary_lease_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    canary_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_dual_write_canary_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_write_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    to_write_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canary_object_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    canary_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    canary_write_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    routable_dual_write_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
