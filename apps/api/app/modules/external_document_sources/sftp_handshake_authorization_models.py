from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class _SftpHandshakeAuthorizationSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    secret_resolution_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    credential_stored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    provider_network_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    authentication_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    sftp_session_opened: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_list_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_read_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_write_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_delete_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    evidence_admitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    document_created: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    processing_enqueued: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    ai_executed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    claim_mutated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    sftp_handshake_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


def _safety_constraints(prefix: str):
    false_fields = (
        ("secret_resolution_performed", "resolution"),
        ("credential_stored", "credential"),
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
        CheckConstraint(
            "credential_reference_stored = true",
            name=f"ck_{prefix}_reference",
        ),
        *(
            CheckConstraint(
                f"{field} = false",
                name=f"ck_{prefix}_no_{suffix}",
            )
            for field, suffix in false_fields
        ),
    )


class ExternalDocumentSourceSftpHandshakeAuthorization(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpHandshakeAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_handshake_auths"
    __table_args__ = (
        UniqueConstraint(
            "health_qualification_id",
            name="uq_ext_doc_sftp_hs_auth_health",
        ),
        UniqueConstraint(
            "organization_id",
            "profile_id",
            "request_key",
            name="uq_ext_doc_sftp_hs_auth_request",
        ),
        CheckConstraint(
            "provider_kind = 'sftp'",
            name="ck_ext_doc_sftp_hs_auth_provider",
        ),
        CheckConstraint(
            "health_result_status = 'qualified'",
            name="ck_ext_doc_sftp_hs_auth_qualified",
        ),
        CheckConstraint(
            "authentication_kind IN ('password','private_key')",
            name="ck_ext_doc_sftp_hs_auth_kind",
        ),
        CheckConstraint(
            "status IN ('pending_second_approval','authorized','rejected','expired')",
            name="ck_ext_doc_sftp_hs_auth_status",
        ),
        CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_ext_doc_sftp_hs_auth_four_eyes",
        ),
        CheckConstraint(
            "execution_limit = 1",
            name="ck_ext_doc_sftp_hs_auth_limit",
        ),
        CheckConstraint(
            "(status = 'authorized' AND sftp_handshake_authorized = true) OR "
            "(status <> 'authorized' AND sftp_handshake_authorized = false)",
            name="ck_ext_doc_sftp_hs_auth_mapping",
        ),
        CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL "
            "AND approved_at IS NULL AND approval_reason IS NULL "
            "AND authorization_hash IS NULL AND authorization_expires_at IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'authorized' AND approved_by_id IS NOT NULL "
            "AND approved_at IS NOT NULL AND approval_reason IS NOT NULL "
            "AND authorization_hash IS NOT NULL AND authorization_expires_at IS NOT NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND authorization_hash IS NULL "
            "AND authorization_expires_at IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL "
            "AND terminal_hash IS NOT NULL) OR "
            "(status = 'expired' AND terminal_at IS NOT NULL "
            "AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_hs_auth_lifecycle",
        ),
        Index(
            "ix_ext_doc_sftp_hs_auth_org_profile",
            "organization_id",
            "profile_id",
        ),
        Index(
            "ix_ext_doc_sftp_hs_auth_org_status",
            "organization_id",
            "status",
        ),
        *_safety_constraints("ext_doc_sftp_hs_auth"),
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
    health_qualification_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "external_doc_source_sftp_cred_health_checks.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    credential_reference_binding_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "external_doc_source_sftp_cred_ref_bindings.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_approval_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authentication_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    resolver_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    health_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_result_status: Mapped[str] = mapped_column(String(24), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
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
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    review_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorization_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    authorization_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceSftpHandshakeAuthorizationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpHandshakeAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_handshake_auth_receipts"
    __table_args__ = (
        UniqueConstraint(
            "authorization_id",
            "sequence_number",
            name="uq_ext_doc_sftp_hs_auth_rcpt_seq",
        ),
        UniqueConstraint(
            "organization_id",
            "receipt_hash",
            name="uq_ext_doc_sftp_hs_auth_rcpt_hash",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="ck_ext_doc_sftp_hs_auth_rcpt_seq",
        ),
        CheckConstraint(
            "event_type IN ('requested','authorized','rejected','expired')",
            name="ck_ext_doc_sftp_hs_auth_rcpt_event",
        ),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval' "
            "AND sftp_handshake_authorized = false) OR "
            "(event_type = 'authorized' AND status_after = 'authorized' "
            "AND sftp_handshake_authorized = true) OR "
            "(event_type = 'rejected' AND status_after = 'rejected' "
            "AND sftp_handshake_authorized = false) OR "
            "(event_type = 'expired' AND status_after = 'expired' "
            "AND sftp_handshake_authorized = false)",
            name="ck_ext_doc_sftp_hs_auth_rcpt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR "
            "(sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_hs_auth_rcpt_chain",
        ),
        Index(
            "ix_ext_doc_sftp_hs_auth_rcpt_seq",
            "authorization_id",
            "sequence_number",
        ),
        *_safety_constraints("ext_doc_sftp_hs_auth_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "external_doc_source_sftp_handshake_auths.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
