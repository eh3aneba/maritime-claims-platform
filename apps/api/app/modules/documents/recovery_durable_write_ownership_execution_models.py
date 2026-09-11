from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _DurableWriteSafetyMixin:
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
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


class EvidenceRecoveryDurableWriteOwnershipLease(UUIDPrimaryKeyMixin, TimestampMixin, _DurableWriteSafetyMixin, Base):
    """One reversible Phase AH durable recovery-write ownership lease."""

    __tablename__ = "evidence_recovery_durable_write_ownership_leases"
    __table_args__ = (
        CheckConstraint("status IN ('active','rolled_back','invalidated')", name="ck_dw_owner_lease_status"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_owner_lease_size"),
        CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_dw_owner_lease_local_size"),
        CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_dw_owner_lease_recovery_size"),
        CheckConstraint("observed_local_hash = source_file_hash", name="ck_dw_owner_lease_local_hash"),
        CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_dw_owner_lease_recovery_hash"),
        CheckConstraint("read_route_version_at_activation >= 1", name="ck_dw_owner_lease_read_ver"),
        CheckConstraint("experimental_write_route_version_at_activation >= 1", name="ck_dw_owner_lease_exp_write_ver"),
        CheckConstraint("durable_route_version_before_activation >= 0", name="ck_dw_owner_lease_before_ver"),
        CheckConstraint(
            "durable_route_version_after_activation = durable_route_version_before_activation + 1",
            name="ck_dw_owner_lease_after_ver",
        ),
        CheckConstraint(
            "((status = 'active' AND durable_write_ownership_active = true AND durable_write_authority_created = true AND write_path_switched = true) "
            "OR (status <> 'active' AND durable_write_ownership_active = false AND durable_write_authority_created = false AND write_path_switched = false))",
            name="ck_dw_owner_lease_state",
        ),
        UniqueConstraint("authorization_id", name="uq_dw_owner_lease_auth"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_dw_owner_lease_org_hash"),
        Index("ix_dw_owner_lease_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_dw_owner_lease_org_doc", "organization_id", "document_id", "status"),
        *_safety_constraints("dw_owner_lease"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_authorization_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_af_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    transition_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_write_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    transition_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    read_route_version_at_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    experimental_write_route_version_at_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    durable_route_version_before_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    durable_route_version_after_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    durable_write_ownership_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceRecoveryDurableWriteOwnershipRoute(UUIDPrimaryKeyMixin, TimestampMixin, _DurableWriteSafetyMixin, Base):
    """Durable recovery write-ownership control plane, separate from bounded experiment routing."""

    __tablename__ = "evidence_recovery_durable_write_ownership_routes"
    __table_args__ = (
        CheckConstraint("write_mode IN ('local_only','recovery_primary')", name="ck_dw_owner_route_mode"),
        CheckConstraint("route_version >= 1", name="ck_dw_owner_route_ver"),
        CheckConstraint(
            "((write_mode = 'local_only' AND active_durable_write_ownership_lease_id IS NULL AND durable_write_authority_created = false AND write_path_switched = false) "
            "OR (write_mode = 'recovery_primary' AND active_durable_write_ownership_lease_id IS NOT NULL AND durable_write_authority_created = true AND write_path_switched = true))",
            name="ck_dw_owner_route_state",
        ),
        UniqueConstraint("document_id", name="uq_dw_owner_route_document"),
        Index("ix_dw_owner_route_org_claim", "organization_id", "claim_id"),
        *_safety_constraints("dw_owner_route"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    write_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="local_only", server_default="local_only")
    active_durable_write_ownership_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    changed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecoveryDurableWriteOwnershipReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _DurableWriteSafetyMixin, Base):
    """Append-only receipt for Phase AH durable write-route state transitions."""

    __tablename__ = "evidence_recovery_durable_write_ownership_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('activated','rolled_back','invalidated')", name="ck_dw_owner_rec_phase"),
        CheckConstraint("from_write_mode IN ('local_only','recovery_primary')", name="ck_dw_owner_rec_from"),
        CheckConstraint("to_write_mode IN ('local_only','recovery_primary')", name="ck_dw_owner_rec_to"),
        CheckConstraint("route_version >= 1", name="ck_dw_owner_rec_ver"),
        CheckConstraint(
            "((phase = 'activated' AND durable_write_ownership_active = true AND durable_write_authority_created = true AND write_path_switched = true) "
            "OR (phase <> 'activated' AND durable_write_ownership_active = false AND durable_write_authority_created = false AND write_path_switched = false))",
            name="ck_dw_owner_rec_state",
        ),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_owner_rec_org_hash"),
        Index("ix_dw_owner_rec_time", "lease_id", "transitioned_at"),
        *_safety_constraints("dw_owner_rec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_write_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    to_write_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_af_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    durable_write_ownership_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    durable_write_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False)
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
