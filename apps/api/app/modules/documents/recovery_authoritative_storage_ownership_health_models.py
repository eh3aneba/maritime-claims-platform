from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _AuthoritativeStorageHealthSafetyMixin:
    local_evidence_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    route_mutation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ownership_mutation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    physical_disposal_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_put_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_overwrite_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_move_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("local_evidence_preserved = true", name=f"ck_{prefix}_local_preserved"),
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("route_mutation_performed = false", name=f"ck_{prefix}_no_route_mut"),
        CheckConstraint("ownership_mutation_performed = false", name=f"ck_{prefix}_no_owner_mut"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write_path"),
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


class EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageHealthSafetyMixin,
    Base,
):
    __tablename__ = "evidence_recovery_auth_storage_health_qualifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval','qualified','rejected','expired','invalidated')",
            name="ck_aso_health_status",
        ),
        CheckConstraint("health_state = 'healthy'", name="ck_aso_health_healthy"),
        CheckConstraint("observed_authority_kind = 'recovery_storage'", name="ck_aso_health_kind"),
        CheckConstraint("observed_ownership_transition_active = true", name="ck_aso_health_active"),
        CheckConstraint("observed_local_authoritative = false", name="ck_aso_health_not_local"),
        CheckConstraint("observed_recovery_authoritative = true", name="ck_aso_health_recovery"),
        CheckConstraint("observed_authoritative_storage_changed = true", name="ck_aso_health_changed"),
        CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_four_eyes"),
        CheckConstraint("phase_ak_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_ak_split"),
        CheckConstraint("phase_aj_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_ajr_split"),
        CheckConstraint("phase_aj_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_aja_split"),
        CheckConstraint("phase_ai_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_air_split"),
        CheckConstraint("phase_ai_qualified_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_aiq_split"),
        CheckConstraint("phase_ah_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_aso_health_ah_split"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_aso_health_size"),
        CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_aso_health_local_size"),
        CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_aso_health_recovery_size"),
        CheckConstraint("observed_local_hash = source_file_hash", name="ck_aso_health_local_hash"),
        CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_aso_health_recovery_hash"),
        CheckConstraint("authority_route_version_at_request >= 1", name="ck_aso_health_route_ver"),
        CheckConstraint("read_route_version_at_request >= 1", name="ck_aso_health_read_ver"),
        CheckConstraint("experimental_write_route_version_at_request >= 1", name="ck_aso_health_exp_ver"),
        CheckConstraint("durable_route_version_at_request >= 1", name="ck_aso_health_durable_ver"),
        UniqueConstraint("authoritative_storage_ownership_lease_id", name="uq_aso_health_lease"),
        UniqueConstraint("organization_id", "health_qualification_hash", name="uq_aso_health_org_hash"),
        Index("ix_aso_health_org_claim", "organization_id", "claim_id", "status"),
        Index("ix_aso_health_org_doc", "organization_id", "document_id", "status"),
        *_safety_constraints("aso_health"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authoritative_storage_ownership_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_ai_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    durable_write_ownership_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    authority_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    read_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    experimental_write_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    durable_route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="recovery_storage", server_default="recovery_storage")
    observed_ownership_transition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    observed_recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")

    phase_ak_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_aj_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_aj_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ai_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ai_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ah_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ag_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ag_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_af_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_af_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ae_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ad_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ad_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

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


class EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageHealthSafetyMixin,
    Base,
):
    __tablename__ = "evidence_recovery_auth_storage_health_receipts"
    __table_args__ = (
        CheckConstraint("phase IN ('requested','qualified','rejected','expired','invalidated')", name="ck_aso_health_rec_phase"),
        CheckConstraint("health_state = 'healthy'", name="ck_aso_health_rec_healthy"),
        CheckConstraint("observed_authority_kind = 'recovery_storage'", name="ck_aso_health_rec_kind"),
        CheckConstraint("observed_ownership_transition_active = true", name="ck_aso_health_rec_active"),
        CheckConstraint("observed_local_authoritative = false", name="ck_aso_health_rec_not_local"),
        CheckConstraint("observed_recovery_authoritative = true", name="ck_aso_health_rec_recovery"),
        CheckConstraint("observed_authoritative_storage_changed = true", name="ck_aso_health_rec_changed"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_aso_health_rec_org_hash"),
        Index("ix_aso_health_rec_time", "health_qualification_id", "transitioned_at"),
        *_safety_constraints("aso_health_rec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    authoritative_storage_ownership_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")
    observed_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="recovery_storage", server_default="recovery_storage")
    observed_ownership_transition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    observed_recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authority_route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
