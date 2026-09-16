from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SUCCESSOR_CHECKPOINT_KIND = "remote_file_snapshot_successor_v1"
PREDECESSOR_CHECKPOINT_GENERATION = 1
SUCCESSOR_CHECKPOINT_GENERATION = 2
MAX_SUCCESSOR_CHECKPOINT_CONTENT_BYTES = 8 * 1024 * 1024


class _CheckpointGenerationSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    credential_reference_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activation_authorization_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_token_acquisition_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_provider_client_health_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_remote_metadata_listing_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_remote_file_content_read_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_remote_content_staging_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_sync_checkpoint_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_change_detection_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_versioned_restaging_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    exact_item_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_transiently_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_content_staged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_generation_advance_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sync_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    subscription_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_authorization_code_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    access_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    refresh_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    id_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    client_secret_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    private_key_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_client_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_response_body_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_logged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    always_true = (
        ("credential_reference_stored", "reference"),
        ("credential_reference_resolution_performed", "resolved"),
        ("activation_authorization_consumed", "activation"),
        ("upstream_token_acquisition_completed", "token"),
        ("upstream_provider_client_health_completed", "health"),
        ("upstream_remote_metadata_listing_completed", "listing"),
        ("upstream_remote_file_content_read_completed", "read_proof"),
        ("upstream_remote_content_staging_completed", "stage"),
        ("upstream_sync_checkpoint_completed", "checkpoint"),
        ("upstream_change_detection_completed", "change"),
        ("upstream_versioned_restaging_completed", "restaging"),
    )
    always_false = (
        ("provider_client_constructed", "client"),
        ("exact_item_metadata_read_performed", "metadata_read"),
        ("remote_content_transiently_observed", "content_observed"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "provider_write"),
        ("remote_delete_performed", "provider_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("durable_content_staged", "staged"),
        ("sync_executed", "sync"),
        ("subscription_created", "subscription"),
        ("credential_stored", "credential"),
        ("oauth_authorization_code_stored", "oauth_code"),
        ("access_token_stored", "access_token"),
        ("refresh_token_stored", "refresh_token"),
        ("id_token_stored", "id_token"),
        ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"),
        ("provider_client_stored", "client_stored"),
        ("provider_response_body_stored", "response_body"),
        ("remote_content_returned", "content_returned"),
        ("remote_content_logged", "content_logged"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("claim_mutated", "claim"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in always_true),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in always_false),
    )


class ExternalDocumentSourceCheckpointGenerationExecution(UUIDPrimaryKeyMixin, TimestampMixin, _CheckpointGenerationSafetyMixin, Base):
    __tablename__ = "external_doc_source_checkpoint_generation_execs"
    __table_args__ = (
        UniqueConstraint("versioned_restaging_execution_id", name="uq_ext_doc_cg_exec_restage"),
        UniqueConstraint("predecessor_sync_checkpoint_execution_id", name="uq_ext_doc_cg_exec_predecessor"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_cg_exec_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_cg_exec_provider"),
        CheckConstraint(f"predecessor_checkpoint_generation = {PREDECESSOR_CHECKPOINT_GENERATION}", name="ck_ext_doc_cg_exec_predecessor_generation"),
        CheckConstraint("candidate_generation = 2", name="ck_ext_doc_cg_exec_candidate_generation"),
        CheckConstraint(f"successor_checkpoint_kind = '{SUCCESSOR_CHECKPOINT_KIND}'", name="ck_ext_doc_cg_exec_kind"),
        CheckConstraint(f"successor_checkpoint_generation = {SUCCESSOR_CHECKPOINT_GENERATION}", name="ck_ext_doc_cg_exec_generation"),
        CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_cg_exec_status"),
        CheckConstraint("result_status IS NULL OR result_status = 'checkpoint_generation_advanced'", name="ck_ext_doc_cg_exec_result"),
        CheckConstraint(
            f"content_byte_count >= 0 AND content_byte_count <= {MAX_SUCCESSOR_CHECKPOINT_CONTENT_BYTES}",
            name="ck_ext_doc_cg_exec_size",
        ),
        CheckConstraint(
            "(status = 'requested' AND result_status IS NULL AND completed_at IS NULL AND completion_hash IS NULL "
            "AND checkpoint_created = false AND checkpoint_advanced = false AND checkpoint_generation_advance_completed = false) OR "
            "(status = 'completed' AND result_status = 'checkpoint_generation_advanced' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL "
            "AND checkpoint_created = true AND checkpoint_advanced = true AND checkpoint_generation_advance_completed = true)",
            name="ck_ext_doc_cg_exec_lifecycle",
        ),
        Index("ix_ext_doc_cg_exec_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_cg_exec_restage", "versioned_restaging_execution_id"),
        Index("ix_ext_doc_cg_exec_predecessor", "predecessor_sync_checkpoint_execution_id"),
        Index("ix_ext_doc_cg_exec_org_status", "organization_id", "status"),
        *_safety_constraints("ext_doc_cg_exec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    versioned_restaging_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_versioned_restage_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    predecessor_sync_checkpoint_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sync_checkpoint_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    change_detection_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_change_detect_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    original_staging_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_remote_content_stage_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_remote_metadata_list_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    metadata_item_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_remote_metadata_list_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    predecessor_checkpoint_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=PREDECESSOR_CHECKPOINT_GENERATION, server_default=str(PREDECESSOR_CHECKPOINT_GENERATION))
    predecessor_checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    predecessor_checkpoint_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    successor_checkpoint_kind: Mapped[str] = mapped_column(String(64), nullable=False, default=SUCCESSOR_CHECKPOINT_KIND, server_default=SUCCESSOR_CHECKPOINT_KIND)
    successor_checkpoint_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=SUCCESSOR_CHECKPOINT_GENERATION, server_default=str(SUCCESSOR_CHECKPOINT_GENERATION))
    successor_checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested", server_default="requested")
    result_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceCheckpointGenerationReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _CheckpointGenerationSafetyMixin, Base):
    __tablename__ = "external_doc_source_checkpoint_generation_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_cg_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_cg_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_cg_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_cg_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND checkpoint_created = false AND checkpoint_advanced = false AND checkpoint_generation_advance_completed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND checkpoint_created = true AND checkpoint_advanced = true AND checkpoint_generation_advance_completed = true)",
            name="ck_ext_doc_cg_rcpt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_cg_rcpt_chain"),
        Index("ix_ext_doc_cg_rcpt_seq", "execution_id", "sequence_number"),
        *_safety_constraints("ext_doc_cg_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_checkpoint_generation_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
