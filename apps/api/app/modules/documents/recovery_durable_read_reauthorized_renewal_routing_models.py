from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryDurableReadReauthorizedRenewalLease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bounded reversible read-only renewal lease backed by Phase R."""

    __tablename__ = "evidence_recovery_drr_reauthorized_renewal_leases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')",
            name="ck_drr_reauth_renew_status",
        ),
        CheckConstraint(
            "prepared_by_id <> activated_by_id OR activated_by_id IS NULL",
            name="ck_drr_reauth_renew_four_eyes",
        ),
        CheckConstraint(
            "reauthorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL",
            name="ck_drr_reauth_renew_r_approver_split",
        ),
        CheckConstraint(
            "phase_q_qualified_by_id <> activated_by_id OR activated_by_id IS NULL",
            name="ck_drr_reauth_renew_q_split",
        ),
        CheckConstraint(
            "prior_renewal_activated_by_id <> activated_by_id OR activated_by_id IS NULL",
            name="ck_drr_reauth_renew_p_activator_split",
        ),
        CheckConstraint(
            "((status = 'activated' AND routable_authority_created = true AND durable_read_route_created = true AND read_path_switched = true) OR "
            "(status <> 'activated' AND routable_authority_created = false AND durable_read_route_created = false AND read_path_switched = false))",
            name="ck_drr_reauth_renew_state_flags",
        ),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_drr_reauth_renew_source_size"),
        CheckConstraint("verified_durable_read_count >= 1", name="ck_drr_reauth_renew_verified_reads"),
        CheckConstraint("integrity_failure_count = 0", name="ck_drr_reauth_renew_no_integrity"),
        CheckConstraint("storage_unavailable_count = 0", name="ck_drr_reauth_renew_no_storage_fail"),
        CheckConstraint("route_version_at_prepare >= 1", name="ck_drr_reauth_renew_route_version"),
        CheckConstraint("write_path_switched = false", name="ck_drr_reauth_renew_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_drr_reauth_renew_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_drr_reauth_renew_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_drr_reauth_renew_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_drr_reauth_renew_no_s3_delete"),
        CheckConstraint("local_delete_performed = false", name="ck_drr_reauth_renew_no_local_delete"),
        UniqueConstraint("reauthorization_id", name="uq_drr_reauth_renew_reauthorization"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_drr_reauth_renew_org_hash"),
        Index("ix_drr_reauth_renew_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_drr_reauth_renew_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorization_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_q_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_renewal_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    prior_renewal_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_renewal_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    reauthorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reauthorization_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reauthorization_integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reauthorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_q_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_renewal_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    route_version_at_prepare: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared", server_default="prepared")
    activation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    route_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reauthorization_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_q_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    prior_renewal_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    prepared_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    preparation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    activated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rolled_back_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class EvidenceRecoveryDurableReadReauthorizedRenewalReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only Phase S transition receipt."""

    __tablename__ = "evidence_recovery_drr_reauthorized_renewal_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')",
            name="ck_drr_reauth_renew_rec_phase",
        ),
        CheckConstraint(
            "from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')",
            name="ck_drr_reauth_renew_rec_route",
        ),
        CheckConstraint("route_version >= 1", name="ck_drr_reauth_renew_rec_version"),
        CheckConstraint("write_path_switched = false", name="ck_drr_reauth_renew_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_drr_reauth_renew_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_drr_reauth_renew_rec_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_drr_reauth_renew_rec_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_drr_reauth_renew_rec_no_s3del"),
        CheckConstraint("local_delete_performed = false", name="ck_drr_reauth_renew_rec_no_localdel"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_drr_reauth_renew_rec_org_hash"),
        Index("ix_drr_reauth_renew_rec_time", "reauthorized_renewal_lease_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorized_renewal_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorized_renewal_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    reauthorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_route_class: Mapped[str] = mapped_column(String(24), nullable=False)
    to_route_class: Mapped[str] = mapped_column(String(24), nullable=False)
    route_authority_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reauthorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
