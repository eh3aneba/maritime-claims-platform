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


class _DueTickObservationSafetyMixin:
    schedule_authority_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_lineage_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    due_tick_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    exact_item_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

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
    background_worker_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("schedule_authority_verified", "schedule"),
        ("family_binding_verified", "family"),
        ("current_document_verified", "current"),
        ("provider_lineage_verified", "provider"),
        ("due_tick_verified", "tick"),
        ("provider_client_constructed", "client"),
        ("exact_item_metadata_read_performed", "metadata"),
    )
    false_fields = (
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
        ("background_worker_started", "worker"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceDueTickObservationExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _DueTickObservationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_due_tick_observation_execs"
    __table_args__ = (
        UniqueConstraint("schedule_id", "due_at", name="uq_ext_doc_due_obs_tick"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_due_obs_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_due_obs_provider"),
        CheckConstraint("current_version_number >= 1", name="ck_ext_doc_due_obs_version"),
        CheckConstraint("schedule_revision_number >= 1", name="ck_ext_doc_due_obs_revision"),
        CheckConstraint("cadence_minutes >= 60", name="ck_ext_doc_due_obs_cadence"),
        CheckConstraint("result_status IN ('unchanged','changed','missing')", name="ck_ext_doc_due_obs_result"),
        CheckConstraint("status = 'completed'", name="ck_ext_doc_due_obs_status"),
        CheckConstraint("observed_byte_size IS NULL OR observed_byte_size >= 0", name="ck_ext_doc_due_obs_size"),
        CheckConstraint(
            "(result_status = 'missing' AND observed_projection_hash IS NULL AND observed_display_name_hash IS NULL) OR "
            "(result_status IN ('unchanged','changed') AND observed_projection_hash IS NOT NULL AND observed_display_name_hash IS NOT NULL)",
            name="ck_ext_doc_due_obs_observed",
        ),
        Index("ix_ext_doc_due_obs_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_due_obs_schedule", "schedule_id", "due_at"),
        Index("ix_ext_doc_due_obs_family", "binding_id", "completed_at"),
        *_safety_constraints("ext_doc_due_obs"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    current_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_lineage_observation_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_gen3_change_detect_execs.id", ondelete="RESTRICT"), nullable=False)
    provider_lineage_checkpoint_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_checkpoint_gen3_execs.id", ondelete="RESTRICT"), nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    cadence_class: Mapped[str] = mapped_column(String(32), nullable=False)
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    baseline_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observation_operation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    observation_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_projection_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_display_name_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    observed_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_mime_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", server_default="completed")
    executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    execution_reason: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceDueTickObservationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _DueTickObservationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_due_tick_observation_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_due_obs_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_due_obs_rcpt_seq"),
        CheckConstraint("event_type = 'completed'", name="ck_ext_doc_due_obs_rcpt_event"),
        CheckConstraint("status_after = 'completed'", name="ck_ext_doc_due_obs_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_due_obs_rcpt_prior"),
        *_safety_constraints("ext_doc_due_obs_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_observation_execs.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", server_default="completed")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", server_default="completed")
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
