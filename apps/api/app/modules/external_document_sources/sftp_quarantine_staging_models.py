from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

MAX_SFTP_QUARANTINE_BYTES = 8 * 1024 * 1024
SFTP_QUARANTINE_STORAGE_PURPOSE = "external_sftp_content_quarantine_v1"


class _SftpQuarantineStagingSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_file_content_proof_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    secret_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ssh_transport_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verification_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_transiently_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_reconciliation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_content_staged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    session_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    raw_response_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_logged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_stat_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_rename_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_mkdir_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_chmod_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_chown_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_touch_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    command_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_copy_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


_FALSE_FIELDS = (
    "credential_stored",
    "session_stored",
    "raw_response_stored",
    "remote_content_returned",
    "remote_content_logged",
    "content_parsed",
    "content_extracted",
    "remote_list_performed",
    "remote_stat_performed",
    "remote_write_performed",
    "remote_rename_performed",
    "remote_delete_performed",
    "remote_mkdir_performed",
    "remote_chmod_performed",
    "remote_chown_performed",
    "remote_touch_performed",
    "command_executed",
    "storage_delete_performed",
    "storage_copy_performed",
    "checkpoint_created",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        CheckConstraint("upstream_file_content_proof_completed = true", name=f"ck_{prefix}_upstream"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{idx}") for idx, field in enumerate(_FALSE_FIELDS)),
        CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_hostkey"),
        CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth"),
        CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_sessauth"),
        CheckConstraint("remote_read_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_readsess"),
        CheckConstraint("remote_content_transiently_observed = false OR remote_read_performed = true", name=f"ck_{prefix}_content"),
        CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_closed"),
        CheckConstraint("durable_content_staged = false OR storage_reconciliation_performed = true", name=f"ck_{prefix}_stage"),
        CheckConstraint("remote_content_stored = false OR durable_content_staged = true", name=f"ck_{prefix}_stored"),
    )


class ExternalDocumentSourceSftpQuarantineStaging(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpQuarantineStagingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_quarantine_staging"
    __table_args__ = (
        UniqueConstraint("file_content_proof_id", name="uq_ext_doc_sftp_qstage_proof"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_qstage_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_qstage_provider"),
        CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_sftp_qstage_status"),
        CheckConstraint("result_status IS NULL OR result_status = 'staged_verified'", name="ck_ext_doc_sftp_qstage_result"),
        CheckConstraint(f"expected_content_byte_count >= 0 AND expected_content_byte_count <= {MAX_SFTP_QUARANTINE_BYTES}", name="ck_ext_doc_sftp_qstage_size"),
        CheckConstraint(f"storage_purpose = '{SFTP_QUARANTINE_STORAGE_PURPOSE}'", name="ck_ext_doc_sftp_qstage_purpose"),
        CheckConstraint(
            "(status = 'requested' AND completed_at IS NULL AND completion_hash IS NULL AND result_status IS NULL "
            "AND stored_etag IS NULL AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND ssh_transport_performed = false AND host_key_verification_performed = false AND host_key_verified = false "
            "AND authentication_performed = false AND authentication_succeeded = false AND sftp_session_opened = false "
            "AND sftp_session_closed = false AND remote_content_transiently_observed = false AND remote_read_performed = false "
            "AND storage_reconciliation_performed = false AND durable_content_staged = false AND remote_content_stored = false) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND result_status = 'staged_verified' "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true AND host_key_verified = true "
            "AND authentication_performed = true AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_content_transiently_observed = true AND remote_read_performed = true "
            "AND storage_reconciliation_performed = true AND durable_content_staged = true AND remote_content_stored = true)",
            name="ck_ext_doc_sftp_qstage_lifecycle",
        ),
        Index("ix_ext_doc_sftp_qstage_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_sftp_qstage_org_status", "organization_id", "status"),
        *_safety_constraints("sftp_qstage"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    file_content_proof_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_file_content_proofs.id", ondelete="RESTRICT"), nullable=False, index=True)
    directory_listing_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_entry_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listing_entries.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_activation_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_session_activations.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_cred_ref_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authentication_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    destination_port: Mapped[int] = mapped_column(Integer, nullable=False)
    pinned_host_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_root_path_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    upstream_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    upstream_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    upstream_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    read_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)

    storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False, default=SFTP_QUARANTINE_STORAGE_PURPOSE, server_default=SFTP_QUARANTINE_STORAGE_PURPOSE)
    storage_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stored_etag: Mapped[str | None] = mapped_column(String(256), nullable=True)

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


class ExternalDocumentSourceSftpQuarantineStagingReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpQuarantineStagingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_quarantine_staging_receipts"
    __table_args__ = (
        UniqueConstraint("staging_id", "sequence_number", name="uq_ext_doc_sftp_qstage_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_qstage_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_qstage_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_qstage_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND remote_content_transiently_observed = false AND remote_read_performed = false "
            "AND storage_reconciliation_performed = false AND durable_content_staged = false AND remote_content_stored = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND remote_content_transiently_observed = true AND remote_read_performed = true "
            "AND storage_reconciliation_performed = true AND durable_content_staged = true AND remote_content_stored = true)",
            name="ck_ext_doc_sftp_qstage_rcpt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_qstage_rcpt_chain",
        ),
        Index("ix_ext_doc_sftp_qstage_rcpt_seq", "staging_id", "sequence_number"),
        *_safety_constraints("sftp_qstage_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    staging_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_quarantine_staging.id", ondelete="RESTRICT"), nullable=False, index=True)
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
