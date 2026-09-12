from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _AuthoritativeStorageRatificationExecutionSafetyMixin:
    local_evidence_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    route_mutation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    ownership_mutation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
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
        CheckConstraint("route_mutation_performed = true", name=f"ck_{prefix}_route_mut"),
        CheckConstraint("ownership_mutation_performed = true", name=f"ck_{prefix}_owner_mut"),
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


class EvidenceRecoveryAuthoritativeStorageRatification(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageRatificationExecutionSafetyMixin,
    Base,
):
    """Phase AN durable authoritative recovery-storage ratification artifact."""

    __tablename__ = "evidence_recovery_storage_ratifications"
    __table_args__ = (
        CheckConstraint("status = 'ratified'", name="ck_asr_exec_status"),
        CheckConstraint("authority_kind = 'recovery_storage'", name="ck_asr_exec_kind"),
        CheckConstraint("authority_tenure = 'durable_recovery'", name="ck_asr_exec_tenure"),
        CheckConstraint("ratification_active = true", name="ck_asr_exec_active"),
        CheckConstraint("durable_authority_created = true", name="ck_asr_exec_durable"),
        CheckConstraint("local_authoritative = false", name="ck_asr_exec_not_local"),
        CheckConstraint("recovery_authoritative = true", name="ck_asr_exec_recovery"),
        CheckConstraint("authoritative_storage_changed = true", name="ck_asr_exec_changed"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_asr_exec_size"),
        CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_asr_exec_local_size"),
        CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_asr_exec_recovery_size"),
        CheckConstraint("observed_local_hash = source_file_hash", name="ck_asr_exec_local_hash"),
        CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_asr_exec_recovery_hash"),
        CheckConstraint("authority_route_version_before_ratification >= 1", name="ck_asr_exec_before_ver"),
        CheckConstraint(
            "authority_route_version_after_ratification = authority_route_version_before_ratification + 1",
            name="ck_asr_exec_after_ver",
        ),
        UniqueConstraint("authorization_id", name="uq_asr_exec_auth"),
        UniqueConstraint("organization_id", "ratification_hash", name="uq_asr_exec_org_hash"),
        Index("ix_asr_exec_org_claim", "organization_id", "claim_id"),
        Index("ix_asr_exec_org_doc", "organization_id", "document_id"),
        *_safety_constraints("asr_exec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_storage_ratification_auths.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_approval_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_storage_ratification_auth_receipts.id", ondelete="RESTRICT"), nullable=False)
    phase_al_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    authoritative_storage_ownership_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_aj_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_auth_storage_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_ai_health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    durable_write_ownership_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_write_ownership_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_al_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_al_health_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_al_integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authoritative_storage_ownership_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_aj_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    authority_route_version_before_ratification: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_route_version_after_ratification: Mapped[int] = mapped_column(Integer, nullable=False)
    read_route_version_at_ratification: Mapped[int] = mapped_column(Integer, nullable=False)
    experimental_write_route_version_at_ratification: Mapped[int] = mapped_column(Integer, nullable=False)
    durable_route_version_at_ratification: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ratification_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ratified", server_default="ratified")
    authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="recovery_storage", server_default="recovery_storage")
    authority_tenure: Mapped[str] = mapped_column(String(40), nullable=False, default="durable_recovery", server_default="durable_recovery")
    ratification_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    durable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_reason: Mapped[str] = mapped_column(Text, nullable=False)


class EvidenceRecoveryAuthoritativeStorageRatificationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _AuthoritativeStorageRatificationExecutionSafetyMixin,
    Base,
):
    """Append-only Phase AN durable ownership ratification receipt."""

    __tablename__ = "evidence_recovery_storage_ratification_receipts"
    __table_args__ = (
        CheckConstraint("phase = 'ratified'", name="ck_asr_exec_rec_phase"),
        CheckConstraint("from_authority_kind = 'recovery_storage'", name="ck_asr_exec_rec_from_kind"),
        CheckConstraint("to_authority_kind = 'recovery_storage'", name="ck_asr_exec_rec_to_kind"),
        CheckConstraint("from_authority_tenure = 'bounded_recovery'", name="ck_asr_exec_rec_from_tenure"),
        CheckConstraint("to_authority_tenure = 'durable_recovery'", name="ck_asr_exec_rec_to_tenure"),
        CheckConstraint("route_version >= 1", name="ck_asr_exec_rec_ver"),
        CheckConstraint("ratification_active = true", name="ck_asr_exec_rec_active"),
        CheckConstraint("durable_authority_created = true", name="ck_asr_exec_rec_durable"),
        CheckConstraint("local_authoritative = false", name="ck_asr_exec_rec_not_local"),
        CheckConstraint("recovery_authoritative = true", name="ck_asr_exec_rec_recovery"),
        CheckConstraint("authoritative_storage_changed = true", name="ck_asr_exec_rec_changed"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_asr_exec_rec_org_hash"),
        Index("ix_asr_exec_rec_time", "ratification_id", "transitioned_at"),
        *_safety_constraints("asr_exec_rec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    ratification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_storage_ratifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_storage_ratification_auths.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="ratified", server_default="ratified")
    from_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="recovery_storage", server_default="recovery_storage")
    to_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="recovery_storage", server_default="recovery_storage")
    from_authority_tenure: Mapped[str] = mapped_column(String(40), nullable=False, default="bounded_recovery", server_default="bounded_recovery")
    to_authority_tenure: Mapped[str] = mapped_column(String(40), nullable=False, default="durable_recovery", server_default="durable_recovery")
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_approval_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_al_health_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ratification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ratification_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    durable_authority_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    local_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    recovery_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)