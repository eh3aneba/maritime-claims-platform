from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

MAX_SFTP_CONTENT_PROOF_BYTES = 8 * 1024 * 1024


class _SftpFileContentProofSafetyMixin:
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
    remote_content_transiently_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    session_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    raw_response_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "session_stored",
    "raw_response_stored",
    "remote_content_stored",
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
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{field}") for field in _FALSE_SAFETY_FIELDS),
        CheckConstraint("host_key_verified = false OR host_key_verification_performed = true", name=f"ck_{prefix}_host_key"),
        CheckConstraint("authentication_succeeded = false OR authentication_performed = true", name=f"ck_{prefix}_auth_order"),
        CheckConstraint("sftp_session_opened = false OR authentication_succeeded = true", name=f"ck_{prefix}_session_auth"),
        CheckConstraint("remote_read_performed = false OR sftp_session_opened = true", name=f"ck_{prefix}_read_session"),
        CheckConstraint("remote_content_transiently_observed = false OR remote_read_performed = true", name=f"ck_{prefix}_content_read"),
        CheckConstraint("sftp_session_opened = false OR sftp_session_closed = true", name=f"ck_{prefix}_session_closed"),
    )


class ExternalDocumentSourceSftpFileContentProof(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpFileContentProofSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_file_content_proofs"
    __table_args__ = (
        UniqueConstraint("listing_entry_id", name="uq_ext_doc_sftp_content_proof_entry"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_content_proof_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_content_proof_provider"),
        CheckConstraint("authentication_kind IN ('password','private_key')", name="ck_ext_doc_sftp_content_proof_auth_kind"),
        CheckConstraint("authentication_method IN ('password','public_key')", name="ck_ext_doc_sftp_content_proof_auth_method"),
        CheckConstraint("read_limit = 1", name="ck_ext_doc_sftp_content_proof_read_limit"),
        CheckConstraint(f"max_content_bytes = {MAX_SFTP_CONTENT_PROOF_BYTES}", name="ck_ext_doc_sftp_content_proof_max_bytes"),
        CheckConstraint("result_status = 'read_verified'", name="ck_ext_doc_sftp_content_proof_result"),
        CheckConstraint(
            f"declared_byte_size IS NULL OR (declared_byte_size >= 0 AND declared_byte_size <= {MAX_SFTP_CONTENT_PROOF_BYTES})",
            name="ck_ext_doc_sftp_content_proof_declared_size",
        ),
        CheckConstraint(
            f"content_byte_count >= 0 AND content_byte_count <= {MAX_SFTP_CONTENT_PROOF_BYTES}",
            name="ck_ext_doc_sftp_content_proof_observed_size",
        ),
        CheckConstraint("latency_class IN ('fast','normal','slow')", name="ck_ext_doc_sftp_content_proof_latency"),
        CheckConstraint(
            "secret_resolution_performed = true AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true AND authentication_performed = true "
            "AND authentication_succeeded = true AND sftp_session_opened = true "
            "AND sftp_session_closed = true AND remote_content_transiently_observed = true "
            "AND remote_read_performed = true",
            name="ck_ext_doc_sftp_content_proof_success",
        ),
        CheckConstraint("completed_at >= requested_at", name="ck_ext_doc_sftp_content_proof_time"),
        Index("ix_ext_doc_sftp_content_proof_org_profile", "organization_id", "profile_id"),
        *_safety_constraints("ext_doc_sftp_content_proof"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
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

    listing_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_items_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    read_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    read_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_content_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=MAX_SFTP_CONTENT_PROOF_BYTES, server_default=str(MAX_SFTP_CONTENT_PROOF_BYTES))

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    authentication_method: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_class: Mapped[str] = mapped_column(String(24), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpFileContentProofReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpFileContentProofSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_file_content_proof_receipts"
    __table_args__ = (
        UniqueConstraint("proof_id", "sequence_number", name="uq_ext_doc_sftp_content_proof_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_content_proof_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_content_proof_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_content_proof_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND secret_resolution_performed = false AND provider_network_performed = false "
            "AND remote_content_transiently_observed = false AND remote_read_performed = false) OR "
            "(event_type = 'completed' AND status_after = 'read_verified' "
            "AND secret_resolution_performed = true AND provider_network_performed = true "
            "AND remote_content_transiently_observed = true AND remote_read_performed = true)",
            name="ck_ext_doc_sftp_content_proof_rcpt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_content_proof_rcpt_chain",
        ),
        Index("ix_ext_doc_sftp_content_proof_rcpt_seq", "proof_id", "sequence_number"),
        *_safety_constraints("ext_doc_sftp_content_proof_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    proof_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_file_content_proofs.id", ondelete="RESTRICT"), nullable=False, index=True)
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
