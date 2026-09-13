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
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _PhysicalDisposalClosureSafetyMixin:
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
        CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("route_mutation_performed = false", name=f"ck_{prefix}_no_route"),
        CheckConstraint("ownership_mutation_performed = false", name=f"ck_{prefix}_no_owner"),
        CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write_path"),
        CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        CheckConstraint("physical_disposal_authorized = false", name=f"ck_{prefix}_no_authority"),
        CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        CheckConstraint("local_overwrite_performed = false", name=f"ck_{prefix}_no_overwrite"),
        CheckConstraint("local_move_performed = false", name=f"ck_{prefix}_no_move"),
        CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    )


class PhysicalDisposalClosureQualification(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _PhysicalDisposalClosureSafetyMixin,
    Base,
):
    """Independent Phase 17.4-C observation of one successful disposal execution."""

    __tablename__ = "physical_disposal_closure_qualifications"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_pd_close_execution"),
        UniqueConstraint("organization_id", "closure_qualification_hash", name="uq_pd_close_org_hash"),
        CheckConstraint(
            "status IN ('pending_second_approval','qualified','rejected','expired','invalidated')",
            name="ck_pd_close_status",
        ),
        CheckConstraint("health_state = 'healthy'", name="ck_pd_close_health"),
        CheckConstraint("document_count > 0", name="ck_pd_close_doc_count"),
        CheckConstraint("total_file_size_bytes >= 0", name="ck_pd_close_total_bytes"),
        CheckConstraint("observed_local_targets_absent = true", name="ck_pd_close_local_absent"),
        CheckConstraint("observed_recovery_bytes_healthy = true", name="ck_pd_close_recovery_healthy"),
        CheckConstraint("observed_document_rows_preserved = true", name="ck_pd_close_rows_preserved"),
        CheckConstraint("observed_storage_keys_preserved = true", name="ck_pd_close_keys_preserved"),
        CheckConstraint("observed_authority_kind = 'recovery_storage'", name="ck_pd_close_authority_kind"),
        CheckConstraint("observed_authority_tenure = 'durable_recovery'", name="ck_pd_close_authority_tenure"),
        CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_four_eyes"),
        CheckConstraint("phase_17_4_b_executor_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_exec_split"),
        CheckConstraint("phase_17_4_a_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_ar_split"),
        CheckConstraint("phase_17_4_a_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_aa_split"),
        CheckConstraint("review_expires_at > requested_at", name="ck_pd_close_review_window"),
        CheckConstraint(
            "(status = 'pending_second_approval' AND qualified_by_id IS NULL AND qualified_at IS NULL "
            "AND qualification_reason IS NULL AND decision_hash IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'qualified' AND qualified_by_id IS NOT NULL AND qualified_at IS NOT NULL "
            "AND qualification_reason IS NOT NULL AND decision_hash IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('rejected','expired','invalidated') AND qualified_by_id IS NULL AND qualified_at IS NULL "
            "AND qualification_reason IS NULL AND decision_hash IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_pd_close_lifecycle",
        ),
        Index("ix_pd_close_org_claim_status", "organization_id", "claim_id", "status"),
        Index("ix_pd_close_org_execution", "organization_id", "execution_id"),
        *_safety_constraints("pd_close"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("physical_disposal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("physical_disposal_admission_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)

    execution_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_bindings_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_receipt_chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_outcomes_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_snapshot: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    verification_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    separation_actor_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    observed_local_targets_absent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_recovery_bytes_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_document_rows_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_storage_keys_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observed_authority_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="recovery_storage", server_default="recovery_storage")
    observed_authority_tenure: Mapped[str] = mapped_column(String(40), nullable=False, default="durable_recovery", server_default="durable_recovery")
    health_state: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy", server_default="healthy")

    phase_17_4_b_executor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_17_4_a_requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_17_4_a_approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closure_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")

    qualified_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    qualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PhysicalDisposalClosureReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _PhysicalDisposalClosureSafetyMixin,
    Base,
):
    """Append-only hash-chained lifecycle evidence for Phase 17.4-C."""

    __tablename__ = "physical_disposal_closure_receipts"
    __table_args__ = (
        UniqueConstraint("qualification_id", "sequence_number", name="uq_pd_close_receipt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_pd_close_receipt_org_hash"),
        CheckConstraint("sequence_number > 0", name="ck_pd_close_receipt_sequence"),
        CheckConstraint(
            "event_type IN ('requested','qualified','rejected','expired','invalidated')",
            name="ck_pd_close_receipt_event",
        ),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval') OR "
            "(event_type = 'qualified' AND status_after = 'qualified') OR "
            "(event_type = 'rejected' AND status_after = 'rejected') OR "
            "(event_type = 'expired' AND status_after = 'expired') OR "
            "(event_type = 'invalidated' AND status_after = 'invalidated')",
            name="ck_pd_close_receipt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_pd_close_receipt_chain",
        ),
        Index("ix_pd_close_receipt_qual_seq", "qualification_id", "sequence_number"),
        *_safety_constraints("pd_close_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("physical_disposal_closure_qualifications.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("physical_disposal_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    closure_qualification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
