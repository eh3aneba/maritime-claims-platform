from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class _RecurringObservationScheduleSafetyMixin:
    family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    stable_source_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    human_authorization_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    bounded_cadence_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

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
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    background_worker_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("human_authorization_recorded", "human"),
        ("bounded_cadence_verified", "bounded_cadence"),
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
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_worker_started", "worker"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceRecurringObservationSchedule(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _RecurringObservationScheduleSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_recurring_observation_schedules"
    __table_args__ = (
        UniqueConstraint("binding_id", "revision_number", name="uq_ext_doc_obs_sched_revision"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_sched_request"),
        UniqueConstraint("organization_id", "profile_id", "disable_request_key", name="uq_ext_doc_obs_sched_disable_request"),
        UniqueConstraint("active_binding_guard", name="uq_ext_doc_obs_sched_active_guard"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_sched_provider"),
        CheckConstraint("revision_number >= 1", name="ck_ext_doc_obs_sched_revision"),
        CheckConstraint(
            "cadence_class IN ('hourly','every_6_hours','every_12_hours','daily')",
            name="ck_ext_doc_obs_sched_cadence",
        ),
        CheckConstraint(
            "(cadence_class = 'hourly' AND cadence_minutes = 60) OR "
            "(cadence_class = 'every_6_hours' AND cadence_minutes = 360) OR "
            "(cadence_class = 'every_12_hours' AND cadence_minutes = 720) OR "
            "(cadence_class = 'daily' AND cadence_minutes = 1440)",
            name="ck_ext_doc_obs_sched_cadence_minutes",
        ),
        CheckConstraint("status IN ('active','disabled')", name="ck_ext_doc_obs_sched_status"),
        CheckConstraint(
            "(status = 'active' AND active_binding_guard = binding_id "
            "AND disable_request_key IS NULL AND disabled_by_id IS NULL "
            "AND disable_reason IS NULL AND disabled_at IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'disabled' AND active_binding_guard IS NULL "
            "AND disable_request_key IS NOT NULL AND disabled_by_id IS NOT NULL "
            "AND disable_reason IS NOT NULL AND disabled_at IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_obs_sched_lifecycle",
        ),
        Index("ix_ext_doc_obs_sched_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_obs_sched_binding", "binding_id"),
        Index("ix_ext_doc_obs_sched_due", "status", "next_due_at"),
        *_safety_constraints("ext_doc_obs_sched"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    prior_schedule_id: Mapped[UUID | None] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    cadence_class: Mapped[str] = mapped_column(String(32), nullable=False)
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    active_binding_guard: Mapped[UUID | None] = mapped_column(nullable=True)
    authorized_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    authorization_reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    disable_request_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    disabled_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    disable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceRecurringObservationScheduleReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _RecurringObservationScheduleSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_recurring_observation_schedule_receipts"
    __table_args__ = (
        UniqueConstraint("schedule_id", "sequence_number", name="uq_ext_doc_obs_sched_rcpt_seq"),
        CheckConstraint("sequence_number IN (1,2)", name="ck_ext_doc_obs_sched_rcpt_seq"),
        CheckConstraint("event_type IN ('authorized','disabled')", name="ck_ext_doc_obs_sched_rcpt_event"),
        CheckConstraint("status_after IN ('active','disabled')", name="ck_ext_doc_obs_sched_rcpt_status"),
        CheckConstraint(
            "(sequence_number = 1 AND event_type = 'authorized' AND status_after = 'active' "
            "AND prior_receipt_hash IS NULL) OR "
            "(sequence_number = 2 AND event_type = 'disabled' AND status_after = 'disabled' "
            "AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_obs_sched_rcpt_lifecycle",
        ),
        *_safety_constraints("ext_doc_obs_sched_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
