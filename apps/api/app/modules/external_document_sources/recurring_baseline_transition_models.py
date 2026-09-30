from __future__ import annotations

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


class _RecurringBaselineTransitionSafetyMixin:
    refresh_admission_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    refresh_execution_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    originating_observation_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    stable_source_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    schedule_authority_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    human_authorization_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    recurring_baseline_established: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    schedule_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("refresh_admission_verified", "admission"),
        ("refresh_execution_verified", "refresh"),
        ("originating_observation_verified", "observation"),
        ("family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("current_document_verified", "current"),
        ("schedule_authority_verified", "schedule"),
        ("human_authorization_recorded", "human"),
        ("recurring_baseline_established", "baseline"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("remote_metadata_read_performed", "metadata"),
        ("remote_content_read_performed", "content"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("document_mutated", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_mutated", "checkpoint"),
        ("schedule_mutated", "schedule_mutation"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceRecurringBaselineTransition(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _RecurringBaselineTransitionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_recurring_baseline_transitions"
    __table_args__ = (
        UniqueConstraint("refresh_admission_execution_id", name="uq_ext_doc_baseline_trans_admission"),
        UniqueConstraint("current_document_id", name="uq_ext_doc_baseline_trans_document"),
        UniqueConstraint("binding_id", "current_version_number", name="uq_ext_doc_baseline_trans_version"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_baseline_trans_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_baseline_trans_provider"),
        CheckConstraint("current_version_number >= 2", name="ck_ext_doc_baseline_trans_version"),
        CheckConstraint("status = 'established'", name="ck_ext_doc_baseline_trans_status"),
        Index("ix_ext_doc_baseline_trans_binding", "binding_id", "current_version_number"),
        *_safety_constraints("ext_doc_baseline_trans"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=False)
    schedule_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    refresh_admission_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_admission_execs.id", ondelete="RESTRICT"), nullable=False)
    refresh_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_execs.id", ondelete="RESTRICT"), nullable=False)
    originating_observation_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_observation_execs.id", ondelete="RESTRICT"), nullable=False)
    prior_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refresh_admission_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refresh_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    originating_observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    baseline_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    refreshed_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    refreshed_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="established", server_default="established")
    authorized_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    authorization_reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceRecurringBaselineTransitionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _RecurringBaselineTransitionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_recurring_baseline_transition_receipts"
    __table_args__ = (
        UniqueConstraint("transition_id", "sequence_number", name="uq_ext_doc_baseline_trans_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_baseline_trans_rcpt_seq"),
        CheckConstraint("event_type = 'established'", name="ck_ext_doc_baseline_trans_rcpt_event"),
        CheckConstraint("status_after = 'established'", name="ck_ext_doc_baseline_trans_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_baseline_trans_rcpt_prior"),
        *_safety_constraints("ext_doc_baseline_trans_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    transition_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_baseline_transitions.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="established", server_default="established")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="established", server_default="established")
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
