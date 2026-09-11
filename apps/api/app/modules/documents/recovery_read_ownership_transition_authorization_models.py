from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryReadOwnershipTransitionAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-routable Phase U authorization for one later read-ownership transition."""

    __tablename__ = "evidence_recovery_read_ownership_authorizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_rr_owner_auth_status",
        ),
        CheckConstraint("health_state = 'healthy'", name="ck_rr_owner_auth_healthy"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_four_eyes"),
        CheckConstraint("phase_t_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_t_split"),
        CheckConstraint("reauthorized_renewal_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_s_split"),
        CheckConstraint("reauthorization_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_r_split"),
        CheckConstraint("phase_q_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_q_split"),
        CheckConstraint("prior_renewal_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_p_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_rr_owner_auth_size"),
        CheckConstraint("verified_durable_read_count >= 1", name="ck_rr_owner_auth_verified"),
        CheckConstraint("integrity_failure_count = 0", name="ck_rr_owner_auth_integrity"),
        CheckConstraint("storage_unavailable_count = 0", name="ck_rr_owner_auth_storage"),
        CheckConstraint("route_expired_attempt_count >= 0", name="ck_rr_owner_auth_expired"),
        CheckConstraint("operational_event_count >= verified_durable_read_count", name="ck_rr_owner_auth_events"),
        CheckConstraint("route_version_at_request >= 1", name="ck_rr_owner_auth_routever"),
        CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_rr_owner_auth_approved_exp"),
        CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_rr_owner_auth_nonapproved_exp"),
        CheckConstraint("routable_authority_created = false", name="ck_rr_owner_auth_no_route"),
        CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_auth_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_rr_owner_auth_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_rr_owner_auth_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_auth_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_auth_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_auth_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_auth_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_rr_owner_auth_no_localdel"),
        UniqueConstraint("phase_t_health_qualification_id", name="uq_rr_owner_auth_t_health"),
        UniqueConstraint("organization_id", "authorization_hash", name="uq_rr_owner_auth_org_hash"),
        Index("ix_rr_owner_auth_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_rr_owner_auth_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorized_renewal_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorized_renewal_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorized_renewal_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    terminal_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorized_renewal_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_q_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    prior_renewal_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_renewal_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    phase_t_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_t_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_t_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reauthorized_renewal_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reauthorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_q_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_renewal_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_durable_read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    route_expired_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    operational_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    phase_t_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorized_renewal_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorization_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_q_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    prior_renewal_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

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

    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_read_route_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only Phase U governance receipt."""

    __tablename__ = "evidence_recovery_read_ownership_authorization_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested', 'approved', 'rejected', 'expired', 'invalidated')", name="ck_rr_owner_rec_phase"),
        CheckConstraint("routable_authority_created = false", name="ck_rr_owner_rec_no_route"),
        CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_rec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_rr_owner_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_rr_owner_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_rec_no_owner"),
        CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_rec_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_rr_owner_rec_no_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_rr_owner_rec_org_hash"),
        Index("ix_rr_owner_rec_time", "authorization_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorized_renewal_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorized_renewal_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_read_route_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
