from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SFTP_GENERATION3_CHECKPOINT_KIND = "sftp_quarantine_snapshot_generation3_v1"
SFTP_GENERATION3_PREDECESSOR_GENERATION = 2
SFTP_GENERATION3_CHECKPOINT_GENERATION = 3
MAX_SFTP_GENERATION3_CHECKPOINT_BYTES = 8 * 1024 * 1024


class _SftpGeneration3CheckpointSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_checkpoint_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_successor_change_detection_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_generation3_restaging_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

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
    remote_mkdir_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_chmod_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_chown_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_touch_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    command_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_reconciliation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_content_staged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


_FALSE_FIELDS = (
    "secret_resolution_performed", "provider_network_performed", "ssh_transport_performed",
    "host_key_verification_performed", "authentication_performed", "sftp_session_opened",
    "remote_content_transiently_observed", "remote_list_performed", "remote_stat_performed",
    "remote_read_performed", "remote_write_performed", "remote_rename_performed",
    "remote_delete_performed", "remote_mkdir_performed", "remote_chmod_performed",
    "remote_chown_performed", "remote_touch_performed", "command_executed",
    "storage_read_performed", "storage_write_performed", "storage_reconciliation_performed",
    "storage_delete_performed", "storage_copy_performed", "durable_content_staged",
    "credential_stored", "session_stored", "raw_response_stored", "remote_content_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed", "content_extracted",
    "evidence_admitted", "document_created", "processing_enqueued", "ai_executed", "claim_mutated",
)


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_ref"),
        CheckConstraint("upstream_checkpoint_completed = true", name=f"ck_{prefix}_cp"),
        CheckConstraint("upstream_successor_change_detection_completed = true", name=f"ck_{prefix}_obs"),
        CheckConstraint("upstream_generation3_restaging_completed = true", name=f"ck_{prefix}_restage"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_n{idx}") for idx, field in enumerate(_FALSE_FIELDS)),
    )


class ExternalDocumentSourceSftpGeneration3CheckpointAdvancement(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpGeneration3CheckpointSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_generation3_checkpoint_advancements"
    __table_args__ = (
        UniqueConstraint("generation3_restaging_id", name="uq_sftp_g3_cp_adv_restage"),
        UniqueConstraint("predecessor_checkpoint_advancement_id", name="uq_sftp_g3_cp_adv_predecessor"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_sftp_g3_cp_adv_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_sftp_g3_cp_adv_provider"),
        CheckConstraint(f"predecessor_checkpoint_generation = {SFTP_GENERATION3_PREDECESSOR_GENERATION}", name="ck_sftp_g3_cp_adv_pred_gen"),
        CheckConstraint(f"successor_checkpoint_generation = {SFTP_GENERATION3_CHECKPOINT_GENERATION}", name="ck_sftp_g3_cp_adv_succ_gen"),
        CheckConstraint(f"successor_checkpoint_kind = '{SFTP_GENERATION3_CHECKPOINT_KIND}'", name="ck_sftp_g3_cp_adv_kind"),
        CheckConstraint("status IN ('requested','completed')", name="ck_sftp_g3_cp_adv_status"),
        CheckConstraint("result_status IS NULL OR result_status = 'checkpoint_advanced'", name="ck_sftp_g3_cp_adv_result"),
        CheckConstraint(
            f"content_byte_count >= 0 AND content_byte_count <= {MAX_SFTP_GENERATION3_CHECKPOINT_BYTES}",
            name="ck_sftp_g3_cp_adv_size",
        ),
        CheckConstraint(
            "(status = 'requested' AND result_status IS NULL AND completed_at IS NULL AND completion_hash IS NULL "
            "AND checkpoint_created = false AND checkpoint_advanced = false) OR "
            "(status = 'completed' AND result_status = 'checkpoint_advanced' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL "
            "AND checkpoint_created = true AND checkpoint_advanced = true)",
            name="ck_sftp_g3_cp_adv_lifecycle",
        ),
        Index("ix_sftp_g3_cp_adv_org_profile", "organization_id", "profile_id"),
        Index("ix_sftp_g3_cp_adv_org_status", "organization_id", "status"),
        *_safety_constraints("sftp_g3_cp_adv"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    generation3_restaging_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_generation3_restaging.id", ondelete="RESTRICT"), nullable=False, index=True)
    predecessor_checkpoint_advancement_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_checkpoint_advancements.id", ondelete="RESTRICT"), nullable=False, index=True)
    successor_change_detection_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_successor_change_detections.id", ondelete="RESTRICT"), nullable=False, index=True)
    predecessor_successor_restaging_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_successor_restaging.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    predecessor_checkpoint_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    predecessor_checkpoint_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    candidate_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_generation: Mapped[int] = mapped_column(Integer, nullable=False)

    observation_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    successor_checkpoint_kind: Mapped[str] = mapped_column(String(64), nullable=False, default=SFTP_GENERATION3_CHECKPOINT_KIND, server_default=SFTP_GENERATION3_CHECKPOINT_KIND)
    successor_checkpoint_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=SFTP_GENERATION3_CHECKPOINT_GENERATION, server_default=str(SFTP_GENERATION3_CHECKPOINT_GENERATION))
    successor_checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested", server_default="requested")
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpGeneration3CheckpointSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_g3_checkpoint_advancement_receipts"
    __table_args__ = (
        UniqueConstraint("advancement_id", "sequence_number", name="uq_sftp_g3_cp_adv_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_sftp_g3_cp_adv_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_sftp_g3_cp_adv_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_sftp_g3_cp_adv_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND checkpoint_created = false AND checkpoint_advanced = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND checkpoint_created = true AND checkpoint_advanced = true)",
            name="ck_sftp_g3_cp_adv_rcpt_map",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_sftp_g3_cp_adv_rcpt_chain",
        ),
        Index("ix_sftp_g3_cp_adv_rcpt_seq", "advancement_id", "sequence_number"),
        *_safety_constraints("sftp_g3_cp_adv_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    advancement_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_generation3_checkpoint_advancements.id", ondelete="RESTRICT"), nullable=False, index=True)
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
