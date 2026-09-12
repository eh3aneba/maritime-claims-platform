from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _AuthoritativeStorageExecutionPreservationMixin:
    local_evidence_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_route_mutation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    physical_disposal_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_put_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_overwrite_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_move_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _preservation_constraints(prefix: str):
    return (
        CheckConstraint("local_evidence_preserved = true", name=f"ck_{prefix}_local_preserved"),
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("write_route_mutation_performed = false", name=f"ck_{prefix}_no_write_route"),
        CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        CheckConstraint("physical_disposal_authorized = false", name=f"ck_{prefix}_no_disposal"),
        CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        CheckConstraint("local_overwrite_performed = false", name=f"ck_{prefix}_no_overwrite"),
        CheckConstraint("local_move_performed = false", name=f"ck_{prefix}_no_move"),
        CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    )


class EvidenceRecoveryAuthoritativeStorageOwnershipLease(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageExecutionPreservationMixin,
    Base,
):
    """One bounded reversible Phase AK authoritative-storage ownership lease."""

    __tablename__ = "evidence_recovery_auth_storage_leases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','ratified','rolled_back','expired','invalidated')",
            name="ck_aso_exec_lease_status",
        ),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_aso_exec_lease_size"),
        CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_aso_exec_lease_local_size"),
        CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_aso_exec_lease_recovery_size"),
        CheckConstraint("observed_local_hash = source_file_hash", name="ck_aso_exec_lease_local_hash"),
        CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_aso_exec_lease_recovery_hash"),
        CheckConstraint("authority_route_version_before_activation >= 0", name="ck_aso_exec_lease_before_ver"),
        CheckConstraint(
            "authority_route_version_after_activation = authority_route_version_before_activation + 1",
            name="ck_aso_exec_lease_after_ver",
        ),
        CheckConstraint(
            "((status = 'active' AND ownership_transition_active = true AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
            "OR (status = 'ratified' AND ownership_transition_active = false AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
            "OR (status IN ('rolled_back','expired','invalidated') AND ownership_transition_active = false AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false))",
            name="ck_aso_exec_lease_state",
        ),
        UniqueConstraint("authorization_id", name="uq_aso_exec_lease_auth"),
        UniqueConstraint("organization_id", "lease_hash", name="uq_aso_exec_lease_org_hash"),
        Index("ix_aso_exec_lease_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_aso_exec_lease_org_doc", "organization_id", "document_id", "status"),
        *_preservation_constraints("aso_exec_lease"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_authorization_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_ai_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    durable_write_ownership_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_ai_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    durable_write_ownership_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    durable_route_version_at_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_route_version_before_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_route_version_after_activation: Mapped[int] = mapped_column(Integer, nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    ownership_transition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceRecoveryAuthoritativeStorageOwnershipRoute(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageExecutionPreservationMixin,
    Base,
):
    """Single authoritative evidence-storage control plane for one document."""

    __tablename__ = "evidence_recovery_auth_storage_routes"
    __table_args__ = (
        CheckConstraint("authority_kind IN ('local_evidence','recovery_storage')", name="ck_aso_exec_route_kind"),
        CheckConstraint(
            "authority_tenure IN ('local','bounded_recovery','durable_recovery')",
            name="ck_aso_exec_route_tenure",
        ),
        CheckConstraint("route_version >= 1", name="ck_aso_exec_route_ver"),
        CheckConstraint(
            "((authority_kind = 'local_evidence' AND authority_tenure = 'local' AND active_authority_lease_id IS NULL AND durable_ratification_id IS NULL AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false) "
            "OR (authority_kind = 'recovery_storage' AND authority_tenure = 'bounded_recovery' AND active_authority_lease_id IS NOT NULL AND durable_ratification_id IS NULL AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
            "OR (authority_kind = 'recovery_storage' AND authority_tenure = 'durable_recovery' AND active_authority_lease_id IS NULL AND durable_ratification_id IS NOT NULL AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true))",
            name="ck_aso_exec_route_state",
        ),
        UniqueConstraint("document_id", name="uq_aso_exec_route_document"),
        Index("ix_aso_exec_route_org_claim", "organization_id", "claim_id"),
        *_preservation_constraints("aso_exec_route"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="local_evidence", server_default="local_evidence")
    authority_tenure: Mapped[str] = mapped_column(String(40), nullable=False, default="local", server_default="local")
    active_authority_lease_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_auth_storage_leases.id", ondelete="RESTRICT"), nullable=True, index=True)
    durable_ratification_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence_recovery_storage_ratifications.id", ondelete="RESTRICT"), nullable=True, index=True)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    changed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @validates("active_authority_lease_id")
    def _track_bounded_tenure(self, _key: str, value: UUID | None):
        self.authority_tenure = "bounded_recovery" if value is not None else "local"
        return value

    @validates("durable_ratification_id")
    def _track_durable_tenure(self, _key: str, value: UUID | None):
        if value is not None:
            self.authority_tenure = "durable_recovery"
        elif self.active_authority_lease_id is None:
            self.authority_tenure = "local"
        return value


class EvidenceRecoveryAuthoritativeStorageOwnershipReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageExecutionPreservationMixin,
    Base,
):
    """Append-only Phase AK authority-transition receipt."""

    __tablename__ = "evidence_recovery_auth_storage_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('activated','rolled_back','expired','invalidated')", name="ck_aso_exec_rec_phase"),
        CheckConstraint("from_authority_kind IN ('local_evidence','recovery_storage')", name="ck_aso_exec_rec_from"),
        CheckConstraint("to_authority_kind IN ('local_evidence','recovery_storage')", name="ck_aso_exec_rec_to"),
        CheckConstraint("route_version >= 1", name="ck_aso_exec_rec_ver"),
        CheckConstraint(
            "((phase = 'activated' AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
            "OR (phase <> 'activated' AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false))",
            name="ck_aso_exec_rec_state",
        ),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_aso_exec_rec_org_hash"),
        Index("ix_aso_exec_rec_time", "lease_id", "transitioned_at"),
        *_preservation_constraints("aso_exec_rec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    from_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    to_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_ai_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)