from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ObservationReviewHandoffSafetyMixin:
    observation_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    eligible_result_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    historical_snapshot_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    projector_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    human_user_impersonated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    token_acquired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
        ("observation_integrity_verified", "observation"),
        ("eligible_result_verified", "eligible"),
        ("historical_snapshot_preserved", "snapshot"),
        ("projector_identity_verified", "projector"),
    )
    false_fields = (
        ("human_user_impersonated", "human_impersonation"),
        ("provider_client_constructed", "client"),
        ("token_acquired", "token"),
        ("remote_list_performed", "list"),
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


class ExternalDocumentSourceObservationReviewHandoff(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationReviewHandoffSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_review_handoffs"
    __table_args__ = (
        UniqueConstraint("observation_execution_id", name="uq_ext_doc_obs_review_observation"),
        CheckConstraint("result_status IN ('changed','missing')", name="ck_ext_doc_obs_review_result"),
        CheckConstraint(
            "(result_status = 'missing' AND observed_projection_hash IS NULL) OR "
            "(result_status = 'changed' AND observed_projection_hash IS NOT NULL)",
            name="ck_ext_doc_obs_review_projection",
        ),
        CheckConstraint("status = 'pending'", name="ck_ext_doc_obs_review_status"),
        CheckConstraint("observed_version_number >= 1", name="ck_ext_doc_obs_review_version"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_review_provider"),
        Index("ix_ext_doc_obs_review_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_obs_review_pending", "organization_id", "status", "projected_at"),
        *_safety_constraints("ext_doc_obs_review"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    observation_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_observation_execs.id", ondelete="RESTRICT"), nullable=False)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    observed_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    observed_version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_projection_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    projector_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceObservationReviewHandoffReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationReviewHandoffSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_review_handoff_receipts"
    __table_args__ = (
        UniqueConstraint("handoff_id", "sequence_number", name="uq_ext_doc_obs_review_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_review_rcpt_seq"),
        CheckConstraint("event_type = 'projected'", name="ck_ext_doc_obs_review_rcpt_event"),
        CheckConstraint("status_after = 'pending'", name="ck_ext_doc_obs_review_rcpt_status"),
        *_safety_constraints("ext_doc_obs_review_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    handoff_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_handoffs.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="projected", server_default="projected")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    projector_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
