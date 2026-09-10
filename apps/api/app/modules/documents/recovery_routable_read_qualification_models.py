from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryRoutableReadQualification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-routable governance evidence for repeated successful recovery read cutovers."""

    __tablename__ = "evidence_recovery_routable_read_qualifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'qualified', 'rejected', 'invalidated')",
            name="ck_recovery_read_qual_status",
        ),
        CheckConstraint(
            "first_cutover_lease_id <> second_cutover_lease_id",
            name="ck_recovery_read_qual_distinct_leases",
        ),
        CheckConstraint(
            "first_authorization_id <> second_authorization_id",
            name="ck_recovery_read_qual_distinct_auths",
        ),
        CheckConstraint(
            "requested_by_id <> qualified_by_id OR qualified_by_id IS NULL",
            name="ck_recovery_read_qual_four_eyes",
        ),
        CheckConstraint(
            "first_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL",
            name="ck_recovery_read_qual_first_activator_split",
        ),
        CheckConstraint(
            "second_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL",
            name="ck_recovery_read_qual_second_activator_split",
        ),
        CheckConstraint("successful_cycle_count = 2", name="ck_recovery_read_qual_two_cycles"),
        CheckConstraint("route_version_at_request >= 1", name="ck_recovery_read_qual_route_version"),
        CheckConstraint("routable_authority_created = false", name="ck_recovery_read_qual_no_route_auth"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_read_qual_no_read_switch"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_read_qual_no_write_switch"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_qual_no_key_mut"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_qual_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_qual_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_read_qual_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_read_qual_no_local_del"),
        UniqueConstraint(
            "organization_id",
            "document_id",
            "qualification_bundle_hash",
            name="uq_recovery_read_qual_bundle",
        ),
        UniqueConstraint(
            "organization_id",
            "qualification_hash",
            name="uq_recovery_read_qual_org_hash",
        ),
        Index("ix_recovery_read_qual_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_recovery_read_qual_org_doc_status", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    first_cutover_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    second_cutover_lease_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_leases.id", ondelete="RESTRICT"), nullable=False, index=True)
    first_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    second_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    first_activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    first_rollback_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    second_activation_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    second_rollback_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_read_path_cutover_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)

    first_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    second_lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_rollback_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    second_activation_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    second_rollback_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_cycle_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    second_cycle_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    successful_cycle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")

    first_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    second_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    read_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    write_path_switched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authoritative_storage_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class EvidenceRecoveryRoutableReadQualificationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only governance receipt for routable read qualification transitions."""

    __tablename__ = "evidence_recovery_routable_read_qualification_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('requested', 'qualified', 'rejected', 'invalidated')",
            name="ck_recovery_read_qual_receipt_phase",
        ),
        CheckConstraint("routable_authority_created = false", name="ck_recovery_read_qual_rec_no_route"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_read_qual_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_read_qual_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_qual_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_qual_rec_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_qual_rec_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_read_qual_rec_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_read_qual_rec_no_local_del"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_read_qual_rec_org_hash"),
        Index("ix_recovery_read_qual_receipt_time", "qualification_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_read_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    qualification_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
