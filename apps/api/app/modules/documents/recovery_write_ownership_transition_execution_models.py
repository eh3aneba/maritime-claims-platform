from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ExecutionSafetyMixin:
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_put_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_overwrite_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_move_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _execution_safety_constraints(prefix: str):
    return (
        CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_storage_write"),
        CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
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


class EvidenceRecoveryWriteOwnershipTransitionLease(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ExecutionSafetyMixin,
    Base,
):
    """One bounded Phase AE write-routing ownership transition lease."""

    __tablename__ = "evidence_recovery_write_ownership_transition_leases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','rolled_back','expired','invalidated')",
            name="ck_wr_owner_lease_status",
        ),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_wr_owner_lease_source_size"),
        CheckConstraint(
            "observed_replica_size_bytes = source_file_size_bytes",
            name="ck_wr_owner_lease_replica_size",
        ),
        CheckConstraint(
            "observed_replica_hash = source_file_hash",
            name="ck_wr_owner_lease_replica_hash",
        ),
        CheckConstraint("read_route_version_at_activation >= 1", name="ck_wr_owner_lease_read_ver"),
        CheckConstraint("write_route_version_before_activation >= 1", name="ck_wr_owner_lease_write_before"),
        CheckConstraint(
            "write_route_version_after_activation = write_route_version_before_activation + 1",
            name="ck_wr_owner_lease_write_after",
        ),
        CheckConstraint(
            "route_expires_at > activated_at",
            name="ck_wr_owner_lease_window",
        ),
        CheckConstraint(
            "((status = 'active' AND bounded_write_ownership_transition_active = true AND write_path_switched = true) "
            "OR (status <> 'active' AND bounded_write_ownership_transition_active = false AND write_path_switched = false))",
            name="ck_wr_owner_lease_state_flags",
        ),
        *_execution_safety_constraints("wr_owner_lease"),
        UniqueConstraint("authorization_id", name="uq_wr_owner_lease_authorization"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_wr_owner_lease_org_hash"),
        Index("ix_wr_owner_lease_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_wr_owner_lease_org_doc", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_write_ownership_transition_authorizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_write_ownership_transition_auth_receipts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    phase_ac_health_qualification_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_routable_dual_write_canary_health_qualifications.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    canary_lease_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_routable_dual_write_canary_leases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    replica_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_ac_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_ac_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canary_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_replica_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_replica_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read_route_version_at_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    write_route_version_before_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    write_route_version_after_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    bounded_write_ownership_transition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    route_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceRecoveryWriteOwnershipTransitionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ExecutionSafetyMixin,
    Base,
):
    """Append-only receipt for Phase AE route state changes."""

    __tablename__ = "evidence_recovery_write_ownership_transition_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('activated','rolled_back','expired','invalidated')",
            name="ck_wr_owner_rec_phase",
        ),
        CheckConstraint(
            "from_write_mode IN ('local_only','recovery_primary') AND "
            "to_write_mode IN ('local_only','recovery_primary')",
            name="ck_wr_owner_rec_modes",
        ),
        CheckConstraint("route_version >= 1", name="ck_wr_owner_rec_route_ver"),
        CheckConstraint(
            "((phase = 'activated' AND bounded_write_ownership_transition_active = true AND write_path_switched = true) "
            "OR (phase <> 'activated' AND bounded_write_ownership_transition_active = false AND write_path_switched = false))",
            name="ck_wr_owner_rec_state_flags",
        ),
        *_execution_safety_constraints("wr_owner_rec"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_wr_owner_rec_org_hash"),
        Index("ix_wr_owner_rec_time", "transition_lease_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    transition_lease_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_write_ownership_transition_leases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_write_ownership_transition_authorizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_write_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    to_write_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_ac_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_replica_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bounded_write_ownership_transition_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
