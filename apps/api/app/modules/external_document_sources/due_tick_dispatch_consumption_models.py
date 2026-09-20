from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _DispatchConsumptionSafetyMixin:
    dispatch_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    observation_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    service_executor_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    metadata_observation_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    human_user_impersonated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
        ("dispatch_integrity_verified", "dispatch"),
        ("observation_integrity_verified", "observation"),
        ("service_executor_identity_verified", "service_identity"),
        ("metadata_observation_verified", "metadata"),
    )
    false_fields = (
        ("human_user_impersonated", "human_impersonation"),
        ("remote_list_performed", "list"),
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


class ExternalDocumentSourceDueTickDispatchConsumption(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _DispatchConsumptionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_due_tick_dispatch_consumptions"
    __table_args__ = (
        UniqueConstraint("dispatch_id", name="uq_ext_doc_due_cons_dispatch"),
        UniqueConstraint("observation_execution_id", name="uq_ext_doc_due_cons_observation"),
        CheckConstraint("status IN ('executed','linked_existing')", name="ck_ext_doc_due_cons_status"),
        Index("ix_ext_doc_due_cons_org_dispatch", "organization_id", "dispatch_id"),
        *_safety_constraints("ext_doc_due_cons"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    dispatch_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_dispatches.id", ondelete="RESTRICT"), nullable=False)
    observation_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_observation_execs.id", ondelete="RESTRICT"), nullable=False)
    service_executor_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceDueTickDispatchConsumptionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _DispatchConsumptionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_due_tick_dispatch_consumption_receipts"
    __table_args__ = (
        UniqueConstraint("consumption_id", "sequence_number", name="uq_ext_doc_due_cons_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_due_cons_rcpt_seq"),
        CheckConstraint("event_type = 'consumed'", name="ck_ext_doc_due_cons_rcpt_event"),
        CheckConstraint("status_after IN ('executed','linked_existing')", name="ck_ext_doc_due_cons_rcpt_status"),
        *_safety_constraints("ext_doc_due_cons_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    consumption_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_dispatch_consumptions.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="consumed", server_default="consumed")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    service_executor_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
