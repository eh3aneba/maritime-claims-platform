from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SftpTransportVerificationSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ssh_transport_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verification_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    host_key_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    secret_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    false_fields = (
        ("secret_resolution_performed", "resolution"),
        ("credential_stored", "credential"),
        ("authentication_performed", "authentication"),
        ("sftp_session_opened", "session"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
    )
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceSftpTransportVerification(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpTransportVerificationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_transport_verifications"
    __table_args__ = (
        UniqueConstraint("handshake_execution_id", name="uq_ext_doc_sftp_transport_verify_exec"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_transport_verify_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_transport_verify_provider"),
        CheckConstraint("verification_limit = 1", name="ck_ext_doc_sftp_transport_verify_limit"),
        CheckConstraint("destination_port BETWEEN 1 AND 65535", name="ck_ext_doc_sftp_transport_verify_port"),
        CheckConstraint("result_status IN ('verified','failed')", name="ck_ext_doc_sftp_transport_verify_result"),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'destination_policy_violation','dns_resolution_failed','connection_timeout',"
            "'connection_refused','network_unavailable','ssh_negotiation_failed',"
            "'host_key_mismatch','unsupported_host_key_algorithm','invalid_adapter_result','adapter_error'"
            ")",
            name="ck_ext_doc_sftp_transport_verify_failure",
        ),
        CheckConstraint(
            "latency_class IS NULL OR latency_class IN ('fast','normal','slow')",
            name="ck_ext_doc_sftp_transport_verify_latency",
        ),
        CheckConstraint("checked_at >= requested_at", name="ck_ext_doc_sftp_transport_verify_time"),
        CheckConstraint(
            "(result_status = 'verified' AND failure_code IS NULL AND host_key_algorithm IS NOT NULL "
            "AND latency_class IS NOT NULL AND provider_network_performed = true "
            "AND ssh_transport_performed = true AND host_key_verification_performed = true "
            "AND host_key_verified = true) OR "
            "(result_status = 'failed' AND failure_code IS NOT NULL AND host_key_verified = false)",
            name="ck_ext_doc_sftp_transport_verify_outcome",
        ),
        CheckConstraint(
            "host_key_verified = false OR host_key_verification_performed = true",
            name="ck_ext_doc_sftp_transport_verify_verified",
        ),
        Index("ix_ext_doc_sftp_transport_verify_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_sftp_transport_verify_org_result", "organization_id", "result_status"),
        *_safety_constraints("ext_doc_sftp_transport_verify"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    handshake_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_sftp_handshake_execs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handshake_execution_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handshake_execution_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handshake_execution_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_terminal_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    destination_hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    destination_port: Mapped[int] = mapped_column(Integer, nullable=False)
    pinned_host_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    verification_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host_key_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpTransportVerificationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpTransportVerificationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_transport_verification_receipts"
    __table_args__ = (
        UniqueConstraint("verification_id", "sequence_number", name="uq_ext_doc_sftp_transport_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_transport_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_transport_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_transport_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' "
            "AND provider_network_performed = false AND ssh_transport_performed = false "
            "AND host_key_verification_performed = false AND host_key_verified = false) OR "
            "(event_type = 'completed' AND status_after IN ('verified','failed'))",
            name="ck_ext_doc_sftp_transport_rcpt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_transport_rcpt_chain",
        ),
        Index("ix_ext_doc_sftp_transport_rcpt_seq", "verification_id", "sequence_number"),
        *_safety_constraints("ext_doc_sftp_transport_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    verification_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_sftp_transport_verifications.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
