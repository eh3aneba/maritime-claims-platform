from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryReadOwnershipTransitionHealthQualification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-routable Phase W health evidence for one completed Phase V window."""

    __tablename__ = "evidence_recovery_read_owner_health_qualifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending_second_approval','qualified','degraded','rejected','expired','invalidated')", name="ck_rr_owner_health_status"),
        CheckConstraint("health_state IN ('healthy','degraded','failed')", name="ck_rr_owner_health_state"),
        CheckConstraint("terminal_phase IN ('rolled_back','expired')", name="ck_rr_owner_health_terminal"),
        CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_rr_owner_health_four_eyes"),
        CheckConstraint("transition_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_rr_owner_health_v_split"),
        CheckConstraint("authorization_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_rr_owner_health_u_split"),
        CheckConstraint("verified_read_count >= 1", name="ck_rr_owner_health_verified"),
        CheckConstraint("integrity_failure_count >= 0", name="ck_rr_owner_health_integrity"),
        CheckConstraint("storage_unavailable_count >= 0", name="ck_rr_owner_health_storage"),
        CheckConstraint("route_expired_attempt_count >= 0", name="ck_rr_owner_health_expired"),
        CheckConstraint("operational_event_count >= verified_read_count", name="ck_rr_owner_health_events"),
        CheckConstraint("route_version_at_request >= 1", name="ck_rr_owner_health_routever"),
        CheckConstraint("status <> 'qualified' OR health_state = 'healthy'", name="ck_rr_owner_health_qualified"),
        CheckConstraint("status <> 'degraded' OR health_state <> 'healthy'", name="ck_rr_owner_health_degraded"),
        CheckConstraint("routable_authority_created = false", name="ck_rr_owner_health_no_route"),
        CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_health_no_durable"),
        CheckConstraint("read_ownership_authority_created = false", name="ck_rr_owner_health_no_read_owner"),
        CheckConstraint("read_path_switched = false", name="ck_rr_owner_health_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_rr_owner_health_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_health_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_health_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_health_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_health_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_rr_owner_health_no_localdel"),
        UniqueConstraint("transition_lease_id", name="uq_rr_owner_health_v_lease"),
        UniqueConstraint("organization_id", "health_qualification_hash", name="uq_rr_owner_health_org_hash"),
        Index("ix_rr_owner_health_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_rr_owner_health_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_receipts.id", ondelete="RESTRICT"), nullable=False)
    terminal_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_receipts.id", ondelete="RESTRICT"), nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_t_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauth_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    transition_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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

    terminal_phase: Mapped[str] = mapped_column(String(20), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    storage_unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    route_expired_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    operational_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    transition_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
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

    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_read_route_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_ownership_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryReadOwnershipTransitionHealthReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_recovery_read_owner_health_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','qualified','degraded','rejected','expired','invalidated')", name="ck_rr_owner_health_rec_phase"),
        CheckConstraint("routable_authority_created = false", name="ck_rr_owner_health_rec_route"),
        CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_health_rec_durable"),
        CheckConstraint("read_ownership_authority_created = false", name="ck_rr_owner_health_rec_read_owner"),
        CheckConstraint("read_path_switched = false", name="ck_rr_owner_health_rec_read"),
        CheckConstraint("write_path_switched = false", name="ck_rr_owner_health_rec_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_health_rec_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_health_rec_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_health_rec_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_health_rec_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_rr_owner_health_rec_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_rr_owner_health_rec_org_hash"),
        Index("ix_rr_owner_health_rec_time", "health_qualification_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_owner_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_read_route_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_ownership_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
