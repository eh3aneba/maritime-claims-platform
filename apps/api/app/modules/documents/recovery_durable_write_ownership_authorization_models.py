from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SafetyMixin:
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_route_lease_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_route_reactivated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_put_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_overwrite_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_move_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("write_route_lease_created = false", name=f"ck_{prefix}_no_lease"),
        CheckConstraint("write_route_reactivated = false", name=f"ck_{prefix}_no_reactivate"),
        CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_switch"),
        CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        CheckConstraint("local_overwrite_performed = false", name=f"ck_{prefix}_no_overwrite"),
        CheckConstraint("local_move_performed = false", name=f"ck_{prefix}_no_move"),
        CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    )


class EvidenceRecoveryDurableWriteOwnershipAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    """Phase AG governance authorization for one later durable recovery-write execution."""

    __tablename__ = "evidence_recovery_durable_write_authorizations"
    __table_args__ = (
        CheckConstraint("status IN ('pending_second_approval','approved','rejected','expired','invalidated')", name="ck_dw_auth_status"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_auth_healthy"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_four_eyes"),
        CheckConstraint("phase_af_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_afr_split"),
        CheckConstraint("phase_af_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_afq_split"),
        CheckConstraint("phase_ae_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ae_split"),
        CheckConstraint("phase_ad_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_adr_split"),
        CheckConstraint("phase_ad_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ada_split"),
        CheckConstraint("phase_ac_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ac_split"),
        CheckConstraint("phase_ab_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ab_split"),
        CheckConstraint("phase_aa_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_aar_split"),
        CheckConstraint("phase_aa_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_aaa_split"),
        CheckConstraint("phase_z_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_z_split"),
        CheckConstraint("phase_y_executed_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_y_split"),
        CheckConstraint("phase_x_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_x_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_auth_size"),
        CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_dw_auth_local_size"),
        CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_dw_auth_recovery_size"),
        CheckConstraint("observed_local_hash = source_file_hash", name="ck_dw_auth_local_hash"),
        CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_dw_auth_recovery_hash"),
        CheckConstraint("read_route_version_at_request >= 1", name="ck_dw_auth_read_ver"),
        CheckConstraint("write_route_version_at_request >= 1", name="ck_dw_auth_write_ver"),
        CheckConstraint("max_execution_windows = 1", name="ck_dw_auth_one_window"),
        CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_dw_auth_approved_exp"),
        CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_dw_auth_nonapproved_exp"),
        UniqueConstraint("phase_af_health_qualification_id", name="uq_dw_auth_af_health"),
        UniqueConstraint("organization_id", "authorization_hash", name="uq_dw_auth_org_hash"),
        Index("ix_dw_auth_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_auth_org_doc", "organization_id", "document_id", "status"),
        *_safety_constraints("dw_auth"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_af_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_af_health_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_health_receipts.id", ondelete="RESTRICT"), nullable=False)
    transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ad_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    phase_af_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    transition_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_ad_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_local_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_local_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_recovery_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_recovery_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_recovery_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    write_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    max_execution_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    phase_af_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_af_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ae_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ad_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ad_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ac_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
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


class EvidenceRecoveryDurableWriteOwnershipAuthorizationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _SafetyMixin, Base):
    __tablename__ = "evidence_recovery_durable_write_authorization_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','approved','rejected','expired','invalidated')", name="ck_dw_auth_rec_phase"),
        CheckConstraint("health_state = 'healthy'", name="ck_dw_auth_rec_healthy"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_auth_rec_org_hash"),
        Index("ix_dw_auth_rec_time", "authorization_id", "transitioned_at"),
        *_safety_constraints("dw_auth_rec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_af_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    phase_af_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
