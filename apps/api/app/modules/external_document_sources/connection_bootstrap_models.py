from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ConnectionBootstrapSafetyMixin:
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_token_exchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    subscription_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sync_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authorization_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _no_provider_execution_constraints(prefix: str):
    fields = (
        ("credential_stored", "credential"),
        ("credential_reference_stored", "credential_reference"),
        ("oauth_token_exchanged", "oauth"),
        ("provider_network_performed", "provider_network"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("subscription_created", "subscription"),
        ("sync_executed", "sync"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("claim_mutated", "claim"),
    )
    return tuple(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in fields)


class ExternalDocumentSourceConnectionBootstrapExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ConnectionBootstrapSafetyMixin,
    Base,
):
    __tablename__ = "external_document_source_connection_bootstrap_executions"
    __table_args__ = (
        UniqueConstraint("authorization_id", name="uq_ext_doc_conn_bootstrap_authorization"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_conn_bootstrap_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_conn_bootstrap_provider"),
        CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_conn_bootstrap_status"),
        CheckConstraint(
            "(status = 'requested' AND authorization_terminal_hash IS NULL AND completed_at IS NULL AND completion_hash IS NULL AND authorization_consumed = false) OR "
            "(status = 'completed' AND authorization_terminal_hash IS NOT NULL AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND authorization_consumed = true)",
            name="ck_ext_doc_conn_bootstrap_lifecycle",
        ),
        Index("ix_ext_doc_conn_bootstrap_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_conn_bootstrap_org_status", "organization_id", "status"),
        *_no_provider_execution_constraints("ext_doc_conn_bootstrap"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    discovery_run_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_discovery_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_connection_authorizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_run_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested", server_default="requested")
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceConnectionBootstrapExecutionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ConnectionBootstrapSafetyMixin,
    Base,
):
    __tablename__ = "external_document_source_connection_bootstrap_execution_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_conn_bootstrap_receipt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_conn_bootstrap_receipt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_conn_bootstrap_receipt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_conn_bootstrap_receipt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND authorization_consumed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND authorization_consumed = true)",
            name="ck_ext_doc_conn_bootstrap_receipt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_conn_bootstrap_receipt_chain",
        ),
        Index("ix_ext_doc_conn_bootstrap_receipt_exec_seq", "execution_id", "sequence_number"),
        *_no_provider_execution_constraints("ext_doc_conn_bootstrap_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_connection_bootstrap_executions.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
