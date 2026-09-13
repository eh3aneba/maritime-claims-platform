from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ConnectionAuthorizationSafetyMixin:
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_token_exchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    subscription_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sync_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    live_connection_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _non_execution_constraints(prefix: str):
    return (
        CheckConstraint("credential_stored = false", name=f"ck_{prefix}_no_credential"),
        CheckConstraint("oauth_token_exchanged = false", name=f"ck_{prefix}_no_oauth"),
        CheckConstraint("remote_list_performed = false", name=f"ck_{prefix}_no_list"),
        CheckConstraint("remote_read_performed = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("remote_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("remote_delete_performed = false", name=f"ck_{prefix}_no_delete"),
        CheckConstraint("subscription_created = false", name=f"ck_{prefix}_no_subscription"),
        CheckConstraint("sync_executed = false", name=f"ck_{prefix}_no_sync"),
        CheckConstraint("evidence_admitted = false", name=f"ck_{prefix}_no_evidence"),
        CheckConstraint("document_created = false", name=f"ck_{prefix}_no_document"),
        CheckConstraint("claim_mutated = false", name=f"ck_{prefix}_no_claim"),
    )


class ExternalDocumentSourceConnectionAuthorization(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ConnectionAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_document_source_connection_authorizations"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_conn_auth_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_conn_auth_provider"),
        CheckConstraint("status IN ('pending_second_approval','authorized','rejected','expired')", name="ck_ext_doc_conn_auth_status"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_ext_doc_conn_auth_four_eyes"),
        CheckConstraint("execution_limit = 1", name="ck_ext_doc_conn_auth_execution_limit"),
        CheckConstraint(
            "(status = 'authorized' AND live_connection_authorized = true) OR "
            "(status <> 'authorized' AND live_connection_authorized = false)",
            name="ck_ext_doc_conn_auth_live_mapping",
        ),
        CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND authorization_hash IS NULL AND authorization_expires_at IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'authorized' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND authorization_hash IS NOT NULL AND authorization_expires_at IS NOT NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND authorization_hash IS NULL AND authorization_expires_at IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'expired' AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_conn_auth_lifecycle",
        ),
        Index("ix_ext_doc_conn_auth_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_conn_auth_org_status", "organization_id", "status"),
        *_non_execution_constraints("ext_doc_conn_auth"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    discovery_run_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_discovery_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_run_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")

    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorization_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceConnectionAuthorizationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ConnectionAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_document_source_connection_authorization_receipts"
    __table_args__ = (
        UniqueConstraint("authorization_id", "sequence_number", name="uq_ext_doc_conn_auth_receipt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_conn_auth_receipt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_conn_auth_receipt_seq"),
        CheckConstraint("event_type IN ('requested','authorized','rejected','expired')", name="ck_ext_doc_conn_auth_receipt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval' AND live_connection_authorized = false) OR "
            "(event_type = 'authorized' AND status_after = 'authorized' AND live_connection_authorized = true) OR "
            "(event_type = 'rejected' AND status_after = 'rejected' AND live_connection_authorized = false) OR "
            "(event_type = 'expired' AND status_after = 'expired' AND live_connection_authorized = false)",
            name="ck_ext_doc_conn_auth_receipt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_conn_auth_receipt_chain"),
        Index("ix_ext_doc_conn_auth_receipt_auth_seq", "authorization_id", "sequence_number"),
        *_non_execution_constraints("ext_doc_conn_auth_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_connection_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
