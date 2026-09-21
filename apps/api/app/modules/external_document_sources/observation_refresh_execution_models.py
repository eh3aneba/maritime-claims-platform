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


class _ObservationRefreshExecutionSafetyMixin:
    authorization_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_authority_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_lineage_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    originating_observation_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    exact_item_content_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    durable_content_staged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_response_body_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("authorization_integrity_verified", "authorization"),
        ("current_authority_verified", "authority"),
        ("current_document_verified", "document"),
        ("provider_lineage_verified", "lineage"),
        ("originating_observation_verified", "observation"),
        ("provider_client_constructed", "client"),
        ("exact_item_content_read_performed", "content_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_read_performed", "storage_read"),
        ("durable_content_staged", "staged"),
    )
    false_fields = (
        ("remote_list_performed", "list"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_delete_performed", "storage_delete"),
        ("provider_response_body_stored", "provider_body"),
        ("remote_content_returned", "content_return"),
        ("content_parsed", "parse"),
        ("content_extracted", "extract"),
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


class ExternalDocumentSourceObservationRefreshExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationRefreshExecutionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_refresh_execs"
    __table_args__ = (
        UniqueConstraint("authorization_id", name="uq_ext_doc_obs_refresh_exec_auth"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_refresh_exec_request"),
        CheckConstraint("status = 'completed'", name="ck_ext_doc_obs_refresh_exec_status"),
        CheckConstraint("result_status = 'staged_refresh_verified'", name="ck_ext_doc_obs_refresh_exec_result"),
        CheckConstraint("current_version_number >= 1", name="ck_ext_doc_obs_refresh_exec_version"),
        CheckConstraint("content_byte_count >= 0", name="ck_ext_doc_obs_refresh_exec_size"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_exec_provider"),
        Index("ix_ext_doc_obs_refresh_exec_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_obs_refresh_exec_auth", "authorization_id"),
        *_safety_constraints("ext_doc_obs_refresh_exec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_authorizations.id", ondelete="RESTRICT"), nullable=False)
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_decisions.id", ondelete="RESTRICT"), nullable=False)
    handoff_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_review_handoffs.id", ondelete="RESTRICT"), nullable=False)
    observation_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_due_tick_observation_execs.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    current_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    current_document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    read_operation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    read_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_media_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", server_default="completed")
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, default="staged_refresh_verified", server_default="staged_refresh_verified")
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceObservationRefreshReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationRefreshExecutionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_refresh_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_obs_refresh_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_refresh_rcpt_seq"),
        CheckConstraint("event_type = 'completed'", name="ck_ext_doc_obs_refresh_rcpt_event"),
        CheckConstraint("status_after = 'completed'", name="ck_ext_doc_obs_refresh_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_obs_refresh_rcpt_prior"),
        *_safety_constraints("ext_doc_obs_refresh_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_execs.id", ondelete="RESTRICT"), nullable=False)
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
