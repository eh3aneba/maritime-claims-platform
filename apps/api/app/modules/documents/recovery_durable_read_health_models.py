from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryDurableReadHealthQualification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-routable evidence that one completed durable recovery-read window was operationally healthy."""

    __tablename__ = "evidence_recovery_durable_read_health_qualifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'qualified', 'degraded', 'rejected', 'invalidated')",
            name="ck_durable_read_health_status",
        ),
        CheckConstraint(
            "health_state IN ('healthy', 'degraded', 'failed')",
            name="ck_durable_read_health_state",
        ),
        CheckConstraint(
            "terminal_phase IN ('rolled_back', 'expired')",
            name="ck_durable_read_health_terminal_phase",
        ),
        CheckConstraint(
            "requested_by_id <> qualified_by_id OR qualified_by_id IS NULL",
            name="ck_durable_read_health_four_eyes",
        ),
        CheckConstraint(
            "activated_by_id <> qualified_by_id OR qualified_by_id IS NULL",
            name="ck_durable_read_health_activator_split",
        ),
        CheckConstraint("verified_durable_read_count >= 1", name="ck_durable_read_health_verified_reads"),
        CheckConstraint("integrity_failure_count >= 0", name="ck_durable_read_health_integrity_failures"),
        CheckConstraint("storage_unavailable_count >= 0", name="ck_durable_read_health_storage_failures"),
        CheckConstraint("route_expired_attempt_count >= 0", name="ck_durable_read_health_expired_attempts"),
        CheckConstraint("operational_event_count >= verified_durable_read_count", name="ck_durable_read_health_event_count"),
        CheckConstraint("route_version_at_request >= 1", name="ck_durable_read_health_route_version"),
        CheckConstraint("status <> 'qualified' OR health_state = 'healthy'", name="ck_durable_read_health_qualified_only_healthy"),
        CheckConstraint("status <> 'degraded' OR health_state <> 'healthy'", name="ck_durable_read_health_degraded_not_healthy"),
        CheckConstraint("routable_authority_created = false", name="ck_durable_read_health_no_route_auth"),
        CheckConstraint("durable_read_route_created = false", name="ck_durable_read_health_no_durable_route"),
        CheckConstraint("read_path_switched = false", name="ck_durable_read_health_no_read_switch"),
        CheckConstraint("write_path_switched = false", name="ck_durable_read_health_no_write_switch"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_durable_read_health_no_key_mut"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_durable_read_health_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_durable_read_health_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_durable_read_health_no_s3_delete"),
        CheckConstraint("local_delete_performed = false", name="ck_durable_read_health_no_local_delete"),
        UniqueConstraint("durable_lease_id", name="uq_durable_read_health_lease"),
        UniqueConstraint("organization_id", "health_qualification_hash", name="uq_durable_read_health_org_hash"),
        Index("ix_durable_read_health_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_durable_read_health_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    durable_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    terminal_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_read_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    durable_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_k_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    verified_durable_read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    storage_unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    route_expired_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    operational_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryDurableReadHealthQualificationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only governance receipt for Phase N health-qualification transitions."""

    __tablename__ = "evidence_recovery_durable_read_health_qualification_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('requested', 'qualified', 'degraded', 'rejected', 'invalidated')",
            name="ck_durable_read_health_receipt_phase",
        ),
        CheckConstraint("routable_authority_created = false", name="ck_durable_read_health_rec_no_route"),
        CheckConstraint("durable_read_route_created = false", name="ck_durable_read_health_rec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_durable_read_health_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_durable_read_health_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_durable_read_health_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_durable_read_health_rec_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_durable_read_health_rec_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_durable_read_health_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_durable_read_health_rec_no_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_durable_read_health_rec_org_hash"),
        Index("ix_durable_read_health_receipt_time", "health_qualification_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    durable_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
