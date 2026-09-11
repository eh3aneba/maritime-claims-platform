from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryReadPathCutoverLease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Short-lived lease that may route reads to one verified recovery replica."""

    __tablename__ = "evidence_recovery_read_path_cutover_leases"
    __table_args__ = (
        CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_route_lease_status"),
        CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_route_lease_four_eyes"),
        CheckConstraint("authorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_route_lease_approver_split"),
        CheckConstraint("((status = 'activated' AND read_path_switched = true AND routable_authority_created = true) OR (status <> 'activated' AND read_path_switched = false AND routable_authority_created = false))", name="ck_recovery_route_lease_state_flags"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_route_lease_no_write_switch"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_route_lease_no_key_mut"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_route_lease_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_route_lease_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_route_lease_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_route_lease_no_local_del"),
        UniqueConstraint("authorization_id", name="uq_recovery_route_lease_authorization"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_recovery_route_lease_org_hash"),
        Index("ix_recovery_route_lease_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_recovery_route_lease_org_doc_status", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_authorization_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_transition_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared", server_default="prepared")
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryReadPathRoute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One mutable, non-destructive read-routing pointer per document."""

    __tablename__ = "evidence_recovery_read_path_routes"
    __table_args__ = (
        CheckConstraint("route_class IN ('local_source', 'recovery_replica')", name="ck_recovery_read_route_class"),
        CheckConstraint(
            "((route_class = 'local_source' AND durable_authority_active = false AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_read_ownership_transition_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
            "(route_class = 'recovery_replica' AND durable_authority_active = false AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_read_ownership_transition_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
            "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_read_ownership_transition_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
            "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NOT NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_read_ownership_transition_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
            "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NOT NULL AND active_read_ownership_transition_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
            "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_read_ownership_transition_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))",
            name="ck_recovery_read_route_binding",
        ),
        CheckConstraint("route_version >= 1", name="ck_recovery_read_route_version"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_read_route_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_route_no_key_mut"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_route_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_route_no_destructive"),
        UniqueConstraint("document_id", name="uq_recovery_read_route_document"),
        Index("ix_recovery_read_route_org_claim", "organization_id", "claim_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    route_class: Mapped[str] = mapped_column(String(24), nullable=False, default="local_source", server_default="local_source")
    durable_authority_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    active_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    active_durable_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    active_durable_renewal_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_durable_read_renewal_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    active_durable_reauthorized_renewal_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_drr_reauthorized_renewal_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    active_read_ownership_transition_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_read_ownership_transition_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    active_replica_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    changed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    @property
    def route_authority_kind(self) -> str:
        if self.durable_authority_active:
            if self.active_read_ownership_transition_lease_id is not None:
                return "read_ownership_transition"
            if self.active_durable_reauthorized_renewal_lease_id is not None:
                return "durable_reauthorized_renewal"
            if self.active_durable_renewal_lease_id is not None:
                return "durable_renewal"
            return "durable_promotion"
        if self.route_class == "recovery_replica" and self.active_lease_id is not None:
            return "temporary_cutover"
        return "local"

    @route_authority_kind.setter
    def route_authority_kind(self, value: str) -> None:
        if value not in {"local", "temporary_cutover", "durable_promotion", "durable_renewal", "durable_reauthorized_renewal", "read_ownership_transition"}:
            raise ValueError("Unsupported read route authority kind")
        self.durable_authority_active = value in {"durable_promotion", "durable_renewal", "durable_reauthorized_renewal", "read_ownership_transition"}


class EvidenceRecoveryReadPathCutoverReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only receipt for read-route lease state transitions."""

    __tablename__ = "evidence_recovery_read_path_cutover_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_route_receipt_phase"),
        CheckConstraint("from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')", name="ck_recovery_route_receipt_route_class"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_route_receipt_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_route_receipt_no_key_mut"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_route_receipt_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_route_receipt_no_dest"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_route_receipt_org_hash"),
        Index("ix_recovery_route_receipt_time", "cutover_lease_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    cutover_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_route_class: Mapped[str] = mapped_column(String(24), nullable=False)
    to_route_class: Mapped[str] = mapped_column(String(24), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    routable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
