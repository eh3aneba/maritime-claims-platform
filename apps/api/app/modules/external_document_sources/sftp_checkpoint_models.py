from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SFTP_CHECKPOINT_KIND = "initial_sftp_quarantine_snapshot_v1"
SFTP_CHECKPOINT_GENERATION = 1
MAX_SFTP_CHECKPOINT_CONTENT_BYTES = 8 * 1024 * 1024


class _SftpCheckpointSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_file_content_proof_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_quarantine_staging_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    secret_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ssh_transport_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verification_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_transiently_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_stat_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_rename_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    command_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sync_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    session_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    raw_response_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_logged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


_ALWAYS_FALSE = (
    "secret_resolution_performed", "provider_network_performed", "ssh_transport_performed",
    "host_key_verification_performed", "authentication_performed", "sftp_session_opened",
    "remote_content_transiently_observed", "remote_list_performed", "remote_stat_performed",
    "remote_read_performed", "remote_write_performed", "remote_rename_performed",
    "remote_delete_performed", "command_executed", "storage_read_performed",
    "storage_write_performed", "storage_delete_performed", "storage_copy_performed",
    "sync_executed", "credential_stored", "session_stored", "raw_response_stored",
    "remote_content_stored", "remote_content_returned", "remote_content_logged",
    "content_parsed", "content_extracted", "evidence_admitted", "document_created",
    "processing_enqueued", "ai_executed", "claim_mutated",
)


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        CheckConstraint("upstream_file_content_proof_completed = true", name=f"ck_{prefix}_proof"),
        CheckConstraint("upstream_quarantine_staging_completed = true", name=f"ck_{prefix}_staging"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{idx}") for idx, field in enumerate(_ALWAYS_FALSE)),
    )


class ExternalDocumentSourceSftpCheckpoint(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpCheckpointSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_checkpoints"
    __table_args__ = (
        UniqueConstraint("quarantine_staging_id", name="uq_ext_doc_sftp_checkpoint_stage"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_checkpoint_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_checkpoint_provider"),
        CheckConstraint("status = 'completed'", name="ck_ext_doc_sftp_checkpoint_status"),
        CheckConstraint("result_status = 'checkpoint_recorded'", name="ck_ext_doc_sftp_checkpoint_result"),
        CheckConstraint(f"checkpoint_kind = '{SFTP_CHECKPOINT_KIND}'", name="ck_ext_doc_sftp_checkpoint_kind"),
        CheckConstraint(f"checkpoint_generation = {SFTP_CHECKPOINT_GENERATION}", name="ck_ext_doc_sftp_checkpoint_generation"),
        CheckConstraint(
            f"content_byte_count >= 0 AND content_byte_count <= {MAX_SFTP_CHECKPOINT_CONTENT_BYTES}",
            name="ck_ext_doc_sftp_checkpoint_size",
        ),
        CheckConstraint("checkpoint_created = true", name="ck_ext_doc_sftp_checkpoint_created"),
        CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_checkpoint_time"),
        Index("ix_ext_doc_sftp_checkpoint_org_profile", "organization_id", "profile_id"),
        *_safety_constraints("sftp_checkpoint"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    quarantine_staging_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_quarantine_staging.id", ondelete="RESTRICT"), nullable=False, index=True)
    file_content_proof_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_file_content_proofs.id", ondelete="RESTRICT"), nullable=False, index=True)
    directory_listing_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_entry_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listing_entries.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_content_proof_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    checkpoint_kind: Mapped[str] = mapped_column(String(64), nullable=False, default=SFTP_CHECKPOINT_KIND, server_default=SFTP_CHECKPOINT_KIND)
    checkpoint_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=SFTP_CHECKPOINT_GENERATION, server_default=str(SFTP_CHECKPOINT_GENERATION))
    checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", server_default="completed")
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, default="checkpoint_recorded", server_default="checkpoint_recorded")
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpCheckpointReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpCheckpointSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_checkpoint_receipts"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "sequence_number", name="uq_ext_doc_sftp_checkpoint_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_checkpoint_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_checkpoint_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_checkpoint_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND checkpoint_created = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND checkpoint_created = true)",
            name="ck_ext_doc_sftp_checkpoint_rcpt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_checkpoint_rcpt_chain",
        ),
        Index("ix_ext_doc_sftp_checkpoint_rcpt_seq", "checkpoint_id", "sequence_number"),
        *_safety_constraints("sftp_checkpoint_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    checkpoint_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_checkpoints.id", ondelete="RESTRICT"), nullable=False, index=True)
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
