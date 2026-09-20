from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _DueTickDispatchSafetyMixin:
    schedule_authority_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    due_tick_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    internal_worker_identity_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    db_only_dispatch_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    token_acquired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("schedule_authority_verified", "schedule"),
        ("family_binding_verified", "family"),
        ("current_document_verified", "current"),
        ("due_tick_verified", "tick"),
        ("internal_worker_identity_recorded", "worker"),
        ("db_only_dispatch_verified", "db_only"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("token_acquired", "token"),
        ("remote_metadata_read_performed", "metadata"),
        ("remote_content_read_performed", "content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("document_mutated", "document"),
        ("evidence_admitted", "evidence"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceDueTickDispatch(UUIDPrimaryKeyMixin, TimestampMixin, _DueTickDispatchSafetyMixin, Base):
    __tablename__ = "external_doc_source_due_tick_dispatches"
    __table_args__ = (
        UniqueConstraint("schedule_id", "due_at", name="uq_ext_doc_due_disp_tick"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_due_disp_provider"),
        CheckConstraint("current_version_number >= 1", name="ck_ext_doc_due_disp_version"),
        CheckConstraint("schedule_revision_number >= 1", name="ck_ext_doc_due_disp_revision"),
        CheckConstraint("cadence_minutes >= 60", name="ck_ext_doc_due_disp_cadence"),
        CheckConstraint("status = 'dispatched'", name="ck_ext_doc_due_disp_status"),
        Index("ix_ext_doc_due_disp_due", "due_at", "status"),
        Index("ix_ext_doc_due_disp_schedule", "schedule_id", "due_at"),
        *_safety_constraints("ext_doc_due_disp"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    current_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cadence_class: Mapped[str] = mapped_column(String(32), nullable=False)
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    worker_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="dispatched", server_default="dispatched")
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceDueTickDispatchReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _DueTickDispatchSafetyMixin, Base):
    __tablename__ = "external_doc_source_due_tick_dispatch_receipts"
    __table_args__ = (
        UniqueConstraint("dispatch_id", "sequence_number", name="uq_ext_doc_due_disp_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_due_disp_rcpt_seq"),
        CheckConstraint("event_type = 'dispatched'", name="ck_ext_doc_due_disp_rcpt_event"),
        CheckConstraint("status_after = 'dispatched'", name="ck_ext_doc_due_disp_rcpt_status"),
        *_safety_constraints("ext_doc_due_disp_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    dispatch_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_dispatches.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="dispatched", server_default="dispatched")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="dispatched", server_default="dispatched")
    worker_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
