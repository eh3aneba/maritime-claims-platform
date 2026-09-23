from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SftpCredentialReferenceSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    secret_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
    fields = (
        ("credential_stored", "credential"),
        ("secret_resolution_performed", "secret_resolution"),
        ("provider_network_performed", "provider_network"),
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
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference_only"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in fields),
    )


class ExternalDocumentSourceSftpCredentialReferenceBinding(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpCredentialReferenceSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_cred_ref_bindings"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_ext_doc_sftp_cred_ref_profile"),
        UniqueConstraint(
            "organization_id",
            "profile_id",
            "request_key",
            name="uq_ext_doc_sftp_cred_ref_request",
        ),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_cred_ref_provider"),
        CheckConstraint(
            "authentication_kind IN ('password','private_key')",
            name="ck_ext_doc_sftp_cred_ref_auth",
        ),
        CheckConstraint(
            "reference_backend IN ('aws_secrets_manager','azure_key_vault','gcp_secret_manager','hashicorp_vault')",
            name="ck_ext_doc_sftp_cred_ref_backend",
        ),
        CheckConstraint(
            "status IN ('pending_second_approval','active','rejected','disabled')",
            name="ck_ext_doc_sftp_cred_ref_status",
        ),
        CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_ext_doc_sftp_cred_ref_four_eyes",
        ),
        CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'active' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'disabled' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_cred_ref_lifecycle",
        ),
        Index("ix_ext_doc_sftp_cred_ref_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_sftp_cred_ref_org_status", "organization_id", "status"),
        *_safety_constraints("ext_doc_sftp_cred_ref"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authentication_kind: Mapped[str] = mapped_column(String(32), nullable=False)

    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_name: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_second_approval",
        server_default="pending_second_approval",
    )

    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceSftpCredentialReferenceReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpCredentialReferenceSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_cred_ref_receipts"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "sequence_number",
            name="uq_ext_doc_sftp_cred_ref_receipt_seq",
        ),
        UniqueConstraint(
            "organization_id",
            "receipt_hash",
            name="uq_ext_doc_sftp_cred_ref_receipt_hash",
        ),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_cred_ref_receipt_seq"),
        CheckConstraint(
            "event_type IN ('requested','approved','rejected','disabled')",
            name="ck_ext_doc_sftp_cred_ref_receipt_event",
        ),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval') OR "
            "(event_type = 'approved' AND status_after = 'active') OR "
            "(event_type = 'rejected' AND status_after = 'rejected') OR "
            "(event_type = 'disabled' AND status_after = 'disabled')",
            name="ck_ext_doc_sftp_cred_ref_receipt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_cred_ref_receipt_chain",
        ),
        Index(
            "ix_ext_doc_sftp_cred_ref_receipt_binding_seq",
            "binding_id",
            "sequence_number",
        ),
        *_safety_constraints("ext_doc_sftp_cred_ref_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    binding_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_sftp_cred_ref_bindings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
