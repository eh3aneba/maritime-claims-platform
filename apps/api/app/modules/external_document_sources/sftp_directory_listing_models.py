from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SftpDirectoryListingSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
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
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_stat_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_rename_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    command_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_stored", "credential"),
        ("remote_stat_performed", "stat"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_rename_performed", "rename"),
        ("remote_delete_performed", "delete"),
        ("command_executed", "command"),
        ("checkpoint_created", "checkpoint"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
    )
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
        CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host_key"),
        CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth_order"),
        CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_session_auth"),
        CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_session_closed"),
        CheckConstraint("remote_list_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_list_session"),
    )


class ExternalDocumentSourceSftpDirectoryListing(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpDirectoryListingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_directory_listings"
    __table_args__ = (
        UniqueConstraint("session_activation_id", name="uq_ext_doc_sftp_dir_listing_activation"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_dir_listing_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_dir_listing_provider"),
        CheckConstraint("authentication_kind IN ('password','private_key')", name="ck_ext_doc_sftp_dir_listing_auth_kind"),
        CheckConstraint("listing_limit = 1", name="ck_ext_doc_sftp_dir_listing_limit"),
        CheckConstraint("max_entries = 100", name="ck_ext_doc_sftp_dir_listing_max_entries"),
        CheckConstraint("result_status IN ('listed','failed')", name="ck_ext_doc_sftp_dir_listing_result"),
        CheckConstraint("entry_count >= 0 AND entry_count <= 100", name="ck_ext_doc_sftp_dir_listing_entry_count"),
        CheckConstraint("page_count >= 0 AND page_count <= 1", name="ck_ext_doc_sftp_dir_listing_page_count"),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'credential_resolution_failed','credential_unavailable','connection_failed','connection_timeout',"
            "'host_key_revalidation_failed','authentication_failed','authentication_timeout',"
            "'sftp_subsystem_activation_failed','listing_failed','listing_timeout','path_policy_violation',"
            "'symlink_escape_detected','too_many_entries','oversized_metadata','unsupported_entry_metadata',"
            "'invalid_adapter_result','adapter_error'"
            ")",
            name="ck_ext_doc_sftp_dir_listing_failure",
        ),
        CheckConstraint("latency_class IS NULL OR latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_dir_listing_latency"),
        CheckConstraint(
            "(result_status = 'listed' AND failure_code IS NULL AND page_count = 1 AND items_hash IS NOT NULL "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_list_performed = true) OR "
            "(result_status = 'failed' AND failure_code IS NOT NULL AND entry_count = 0 "
            "AND items_hash IS NULL AND truncated = false)",
            name="ck_ext_doc_sftp_dir_listing_outcome",
        ),
        CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_dir_listing_time"),
        Index("ix_ext_doc_sftp_dir_listing_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_sftp_dir_listing_org_result", "organization_id", "result_status"),
        *_safety_constraints("ext_doc_sftp_dir_listing"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_activation_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_session_activations.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_cred_ref_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_activation_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_activation_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_activation_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authentication_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    destination_port: Mapped[int] = mapped_column(Integer, nullable=False)
    pinned_host_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_root_path: Mapped[str] = mapped_column(String(512), nullable=False)
    remote_root_path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_relative_path: Mapped[str] = mapped_column(String(512), nullable=False, default="", server_default="")
    listing_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    listing_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    items_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpDirectoryListingEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_doc_source_sftp_directory_listing_entries"
    __table_args__ = (
        UniqueConstraint("listing_id", "entry_index", name="uq_ext_doc_sftp_dir_entry_index"),
        UniqueConstraint("listing_id", "entry_hash", name="uq_ext_doc_sftp_dir_entry_hash"),
        CheckConstraint("entry_index >= 0 AND entry_index < 100", name="ck_ext_doc_sftp_dir_entry_index"),
        CheckConstraint("entry_kind IN ('file','directory','symlink','other')", name="ck_ext_doc_sftp_dir_entry_kind"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_ext_doc_sftp_dir_entry_size"),
        Index("ix_ext_doc_sftp_dir_entry_listing", "listing_id", "entry_index"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_index: Mapped[int] = mapped_column(Integer, nullable=False)
    relative_path: Mapped[str] = mapped_column(String(768), nullable=False)
    entry_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpDirectoryListingReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpDirectoryListingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_directory_listing_receipts"
    __table_args__ = (
        UniqueConstraint("listing_id", "sequence_number", name="uq_ext_doc_sftp_dir_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_dir_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_dir_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_dir_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND authentication_performed = false AND sftp_session_opened = false "
            "AND remote_list_performed = false) OR "
            "(event_type = 'completed' AND status_after IN ('listed','failed'))",
            name="ck_ext_doc_sftp_dir_rcpt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_dir_rcpt_chain",
        ),
        Index("ix_ext_doc_sftp_dir_rcpt_seq", "listing_id", "sequence_number"),
        *_safety_constraints("ext_doc_sftp_dir_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_directory_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
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
