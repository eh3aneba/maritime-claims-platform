from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PhysicalDisposalExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Crash-reconcilable execution record for one Phase 17.4-A credential."""

    __tablename__ = "physical_disposal_executions"
    __table_args__ = (
        UniqueConstraint("authorization_id", name="uq_pd_exec_authorization"),
        UniqueConstraint("organization_id", "request_id", name="uq_pd_exec_org_request"),
        UniqueConstraint("organization_id", "execution_request_hash", name="uq_pd_exec_org_req_hash"),
        CheckConstraint("status IN ('prepared','partial','succeeded')", name="ck_pd_exec_status"),
        CheckConstraint("document_count > 0", name="ck_pd_exec_document_count"),
        CheckConstraint("deleted_count >= 0 AND deleted_count <= document_count", name="ck_pd_exec_deleted_count"),
        CheckConstraint("s3_delete_performed = false", name="ck_pd_exec_no_s3_delete"),
        CheckConstraint("document_row_deleted = false", name="ck_pd_exec_no_row_delete"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_pd_exec_no_key_mutation"),
        CheckConstraint(
            "(status = 'prepared' AND completed_at IS NULL AND execution_hash IS NULL) OR "
            "(status = 'partial' AND completed_at IS NULL AND execution_hash IS NULL AND local_delete_performed = true) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL AND execution_hash IS NOT NULL "
            "AND deleted_count = document_count AND destructive_action_performed = true "
            "AND local_delete_performed = true AND recovery_bytes_preserved = true)",
            name="ck_pd_exec_lifecycle",
        ),
        Index("ix_pd_exec_org_claim_status", "organization_id", "claim_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("physical_disposal_admission_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_bindings_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    executor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_reason: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="prepared", server_default="prepared")
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    execution_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    recovery_bytes_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    document_row_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class PhysicalDisposalExecutionItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-document target and outcome evidence for a bounded execution."""

    __tablename__ = "physical_disposal_execution_items"
    __table_args__ = (
        UniqueConstraint("execution_id", "document_id", name="uq_pd_exec_item_document"),
        UniqueConstraint("organization_id", "target_hash", name="uq_pd_exec_item_org_target"),
        CheckConstraint("status IN ('prepared','deleted','verified')", name="ck_pd_exec_item_status"),
        CheckConstraint("file_size_bytes >= 0", name="ck_pd_exec_item_size"),
        CheckConstraint("recovery_verified_before = true", name="ck_pd_exec_item_recovery_before"),
        CheckConstraint("s3_delete_performed = false", name="ck_pd_exec_item_no_s3_delete"),
        CheckConstraint("document_row_deleted = false", name="ck_pd_exec_item_no_row_delete"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_pd_exec_item_no_key_mutation"),
        CheckConstraint(
            "(status = 'prepared' AND local_deleted = false AND local_absent_after = false AND recovery_verified_after = false AND outcome_hash IS NULL) OR "
            "(status = 'deleted' AND local_deleted = true AND local_absent_after = true AND outcome_hash IS NULL) OR "
            "(status = 'verified' AND local_deleted = true AND local_absent_after = true AND recovery_verified_after = true AND outcome_hash IS NOT NULL)",
            name="ck_pd_exec_item_lifecycle",
        ),
        Index("ix_pd_exec_item_exec_status", "execution_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("physical_disposal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    ao_health_qualification_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_recovery_durable_auth_storage_health_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_storage_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_read_source: Mapped[str] = mapped_column(String(80), nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="prepared", server_default="prepared")
    local_existed_before: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    local_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_absent_after: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    recovery_verified_before: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    recovery_verified_after: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_row_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class PhysicalDisposalExecutionReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only hash-chained execution evidence."""

    __tablename__ = "physical_disposal_execution_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_pd_exec_receipt_sequence"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_pd_exec_receipt_org_hash"),
        CheckConstraint("sequence_number > 0", name="ck_pd_exec_receipt_sequence"),
        CheckConstraint("event_type IN ('prepared','local_deleted','reconciled','succeeded')", name="ck_pd_exec_receipt_event"),
        CheckConstraint("status_after IN ('prepared','partial','succeeded')", name="ck_pd_exec_receipt_status"),
        CheckConstraint("s3_delete_performed = false", name="ck_pd_exec_receipt_no_s3_delete"),
        CheckConstraint("document_row_deleted = false", name="ck_pd_exec_receipt_no_row_delete"),
        CheckConstraint("document_storage_key_mutated = false", name="ck_pd_exec_receipt_no_key_mutation"),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_pd_exec_receipt_chain",
        ),
        Index("ix_pd_exec_receipt_exec_seq", "execution_id", "sequence_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("physical_disposal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    execution_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    destructive_action_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    local_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    s3_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    recovery_bytes_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    document_row_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_storage_key_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
