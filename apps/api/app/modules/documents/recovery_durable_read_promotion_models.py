from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceRecoveryDurableReadPromotionAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-routable governance approval for a future durable recovery read promotion."""

    __tablename__ = "evidence_recovery_durable_read_promotion_authorizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_recovery_durable_read_auth_status",
        ),
        CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_recovery_durable_read_auth_four_eyes",
        ),
        CheckConstraint(
            "phase_k_qualified_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_recovery_durable_read_auth_k_qualifier_split",
        ),
        CheckConstraint(
            "first_activated_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_recovery_durable_read_auth_first_activator_split",
        ),
        CheckConstraint(
            "second_activated_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_recovery_durable_read_auth_second_activator_split",
        ),
        CheckConstraint("route_version_at_request >= 1", name="ck_recovery_durable_read_auth_route_version"),
        CheckConstraint("source_file_size_bytes >= 0", name="ck_recovery_durable_read_auth_source_size"),
        CheckConstraint("routable_authority_created = false", name="ck_recovery_durable_read_auth_no_route_auth"),
        CheckConstraint("durable_read_route_created = false", name="ck_recovery_durable_read_auth_no_durable_route"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_durable_read_auth_no_read_switch"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_durable_read_auth_no_write_switch"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_durable_read_auth_no_key_mut"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_durable_read_auth_no_authority"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_durable_read_auth_no_destructive"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_durable_read_auth_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_durable_read_auth_no_local_del"),
        UniqueConstraint("qualification_id", name="uq_recovery_durable_read_auth_qualification"),
        UniqueConstraint("organization_id", "authorization_hash", name="uq_recovery_durable_read_auth_org_hash"),
        Index("ix_recovery_durable_read_auth_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_recovery_durable_read_auth_org_doc_status", "organization_id", "document_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_read_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_read_qualification_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    replica_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_replicas.id", ondelete="RESTRICT"), nullable=False, index=True)

    qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_bucket_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    phase_k_qualified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    first_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    second_activated_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")
    authorization_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class EvidenceRecoveryDurableReadPromotionAuthorizationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only governance receipt for durable read promotion authorization transitions."""

    __tablename__ = "evidence_recovery_durable_read_promotion_authorization_receipts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('requested', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_recovery_durable_read_auth_receipt_phase",
        ),
        CheckConstraint("routable_authority_created = false", name="ck_recovery_durable_read_auth_rec_no_route"),
        CheckConstraint("durable_read_route_created = false", name="ck_recovery_durable_read_auth_rec_no_durable"),
        CheckConstraint("read_path_switched = false", name="ck_recovery_durable_read_auth_rec_no_read"),
        CheckConstraint("write_path_switched = false", name="ck_recovery_durable_read_auth_rec_no_write"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_durable_read_auth_rec_no_key"),
        CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_durable_read_auth_rec_no_auth"),
        CheckConstraint("destructive_action_performed = false", name="ck_recovery_durable_read_auth_rec_no_dest"),
        CheckConstraint("s3_delete_performed = false", name="ck_recovery_durable_read_auth_rec_no_s3_del"),
        CheckConstraint("local_delete_performed = false", name="ck_recovery_durable_read_auth_rec_no_local_del"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_durable_read_auth_rec_org_hash"),
        Index("ix_recovery_durable_read_auth_receipt_time", "authorization_id", "transitioned_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_durable_read_promotion_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_recovery_routable_read_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    integrity_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
