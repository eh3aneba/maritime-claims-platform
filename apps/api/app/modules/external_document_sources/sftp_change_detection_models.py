from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SFTP_CHANGE_RESULTS = ("unchanged", "changed", "missing")
MAX_SFTP_METADATA_BYTE_SIZE = 9223372036854775807


class _SftpChangeDetectionSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_checkpoint_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    secret_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    session_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ssh_transport_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verification_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    exact_item_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    change_detection_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    subscription_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
    "credential_stored", "session_stored", "remote_content_transiently_observed", "remote_list_performed", "remote_read_performed",
    "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
    "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
    "remote_touch_performed", "command_executed", "storage_read_performed",
    "storage_write_performed", "storage_delete_performed", "storage_copy_performed", "checkpoint_advanced", "subscription_created",
    "raw_response_stored", "remote_content_stored", "remote_content_returned",
    "remote_content_logged", "content_parsed", "content_extracted",
    "evidence_admitted", "document_created", "processing_enqueued",
    "ai_executed", "claim_mutated",
)


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_ref"),
        CheckConstraint("upstream_checkpoint_completed = true", name=f"ck_{prefix}_cp"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_n{idx}") for idx, field in enumerate(_FALSE_FIELDS)),
        CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host"),
        CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth"),
        CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_sess"),
        CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_close"),
        CheckConstraint("remote_stat_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_stat"),
        CheckConstraint("exact_item_metadata_read_performed = remote_stat_performed", name=f"ck_{prefix}_meta"),
        CheckConstraint("change_detection_completed = remote_stat_performed", name=f"ck_{prefix}_done"),
    )


class ExternalDocumentSourceSftpChangeDetection(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpChangeDetectionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_change_detections"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", name="uq_ext_doc_sftp_change_checkpoint"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_change_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_change_provider"),
        CheckConstraint("result_status IN ('unchanged','changed','missing')", name="ck_ext_doc_sftp_change_result"),
        CheckConstraint("baseline_entry_kind = 'file'", name="ck_ext_doc_sftp_change_base_kind"),
        CheckConstraint("observed_entry_kind IS NULL OR observed_entry_kind = 'file'", name="ck_ext_doc_sftp_change_obs_kind"),
        CheckConstraint("authentication_method IN ('password','public_key')", name="ck_ext_doc_sftp_change_auth_method"),
        CheckConstraint("latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_change_latency"),
        CheckConstraint(
            "(result_status = 'changed' AND changed_dimensions IS NOT NULL) OR "
            "(result_status IN ('unchanged','missing') AND changed_dimensions IS NULL)",
            name="ck_ext_doc_sftp_change_dimensions",
        ),
        CheckConstraint(
            f"baseline_byte_size IS NULL OR (baseline_byte_size >= 0 AND baseline_byte_size <= {MAX_SFTP_METADATA_BYTE_SIZE})",
            name="ck_ext_doc_sftp_change_base_size",
        ),
        CheckConstraint(
            f"observed_byte_size IS NULL OR (observed_byte_size >= 0 AND observed_byte_size <= {MAX_SFTP_METADATA_BYTE_SIZE})",
            name="ck_ext_doc_sftp_change_obs_size",
        ),
        CheckConstraint(
            "secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_stat_performed = true "
            "AND exact_item_metadata_read_performed = true AND change_detection_completed = true",
            name="ck_ext_doc_sftp_change_execution",
        ),
        CheckConstraint(
            "(result_status = 'missing' AND observed_projection_hash IS NULL "
            "AND observed_entry_kind IS NULL AND observed_byte_size IS NULL AND observed_modified_at IS NULL "
            "AND observed_metadata_id_hash IS NULL AND changed_dimensions IS NULL) OR "
            "(result_status IN ('unchanged','changed') AND observed_projection_hash IS NOT NULL "
            "AND observed_entry_kind = 'file')",
            name="ck_ext_doc_sftp_change_observed",
        ),
        CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_change_time"),
        Index("ix_ext_doc_sftp_change_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_sftp_change_org_result", "organization_id", "result_status"),
        *_safety_constraints("sftp_change"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    checkpoint_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_checkpoints.id", ondelete="RESTRICT"), nullable=False, index=True)
    directory_listing_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_entry_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listing_entries.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_cred_ref_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_relative_path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_entry_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    baseline_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    baseline_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_metadata_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    observation_operation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    observation_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    observation_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authentication_method: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_class: Mapped[str] = mapped_column(String(24), nullable=False)

    observed_projection_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_entry_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    observed_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    observed_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_metadata_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_dimensions: Mapped[str | None] = mapped_column(String(256), nullable=True)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpChangeDetectionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpChangeDetectionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_change_detection_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_sftp_change_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_change_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_change_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_change_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND ssh_transport_performed = false AND host_key_verification_performed = false "
            "AND host_key_verified = false AND authentication_performed = false "
            "AND authentication_succeeded = false AND sftp_session_opened = false "
            "AND sftp_session_closed = false AND remote_stat_performed = false "
            "AND exact_item_metadata_read_performed = false AND change_detection_completed = false) OR "
            "(event_type = 'completed' AND status_after IN ('unchanged','changed','missing') "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_stat_performed = true "
            "AND exact_item_metadata_read_performed = true AND change_detection_completed = true)",
            name="ck_ext_doc_sftp_change_rcpt_map",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_change_rcpt_chain",
        ),
        Index("ix_ext_doc_sftp_change_rcpt_seq", "execution_id", "sequence_number"),
        *_safety_constraints("sftp_change_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_change_detections.id", ondelete="RESTRICT"), nullable=False, index=True)
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
