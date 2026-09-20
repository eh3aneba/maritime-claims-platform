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


class _ObservationReviewDecisionSafetyMixin:
    handoff_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_authority_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    human_decision_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    service_identity_used_as_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


def _decision_safety_constraints(prefix: str):
    true_fields = (
        ("handoff_integrity_verified", "handoff"),
        ("current_authority_verified", "authority"),
        ("current_document_verified", "document"),
        ("human_decision_recorded", "human"),
    )
    false_fields = (
        ("service_identity_used_as_human", "service_human"),
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
        ("document_mutated", "document_mutation"),
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


class ExternalDocumentSourceObservationReviewDecision(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationReviewDecisionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_review_decisions"
    __table_args__ = (
        UniqueConstraint("handoff_id", name="uq_ext_doc_obs_review_dec_handoff"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_review_dec_request"),
        CheckConstraint(
            "decision_kind IN ('approve_refresh','dismiss','acknowledge_missing')",
            name="ck_ext_doc_obs_review_dec_kind",
        ),
        CheckConstraint(
            "status IN ('refresh_authorized','dismissed','missing_acknowledged')",
            name="ck_ext_doc_obs_review_dec_status",
        ),
        CheckConstraint(
            "(result_status = 'changed' AND decision_kind IN ('approve_refresh','dismiss')) OR "
            "(result_status = 'missing' AND decision_kind IN ('acknowledge_missing','dismiss'))",
            name="ck_ext_doc_obs_review_dec_matrix",
        ),
        CheckConstraint(
            "(decision_kind = 'approve_refresh' AND status = 'refresh_authorized') OR "
            "(decision_kind = 'dismiss' AND status = 'dismissed') OR "
            "(decision_kind = 'acknowledge_missing' AND status = 'missing_acknowledged')",
            name="ck_ext_doc_obs_review_dec_lifecycle",
        ),
        CheckConstraint("current_version_number >= 1", name="ck_ext_doc_obs_review_dec_version"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_review_dec_provider"),
        Index("ix_ext_doc_obs_review_dec_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_obs_review_dec_handoff", "handoff_id"),
        *_decision_safety_constraints("ext_doc_obs_review_dec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    handoff_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_handoffs.id", ondelete="RESTRICT"), nullable=False)
    observation_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_observation_execs.id", ondelete="RESTRICT"), nullable=False)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_recurring_observation_schedules.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    current_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    current_document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_provider_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_projection_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceObservationReviewDecisionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationReviewDecisionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_review_decision_receipts"
    __table_args__ = (
        UniqueConstraint("decision_id", "sequence_number", name="uq_ext_doc_obs_review_dec_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_review_dec_rcpt_seq"),
        CheckConstraint(
            "event_type IN ('approve_refresh','dismiss','acknowledge_missing')",
            name="ck_ext_doc_obs_review_dec_rcpt_event",
        ),
        CheckConstraint(
            "status_after IN ('refresh_authorized','dismissed','missing_acknowledged')",
            name="ck_ext_doc_obs_review_dec_rcpt_status",
        ),
        *_decision_safety_constraints("ext_doc_obs_review_dec_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_decisions.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceObservationRefreshAuthorization(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationReviewDecisionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_refresh_authorizations"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_ext_doc_obs_refresh_auth_decision"),
        UniqueConstraint("handoff_id", name="uq_ext_doc_obs_refresh_auth_handoff"),
        CheckConstraint("status = 'authorized'", name="ck_ext_doc_obs_refresh_auth_status"),
        CheckConstraint("execution_limit = 1", name="ck_ext_doc_obs_refresh_auth_limit"),
        CheckConstraint("result_status = 'changed'", name="ck_ext_doc_obs_refresh_auth_result"),
        CheckConstraint("observed_projection_hash IS NOT NULL", name="ck_ext_doc_obs_refresh_auth_projection"),
        CheckConstraint("current_version_number >= 1", name="ck_ext_doc_obs_refresh_auth_version"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_auth_provider"),
        *_decision_safety_constraints("ext_doc_obs_refresh_auth"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    handoff_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_handoffs.id", ondelete="RESTRICT"), nullable=False)
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_decisions.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    current_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    current_document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    prior_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_provider_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    execution_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    authorized_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
