from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ExternalDocumentSourceSafetyMixin:
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


def _safety_constraints(prefix: str):
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
        CheckConstraint("live_connection_authorized = false", name=f"ck_{prefix}_no_live_authority"),
    )


def _non_list_safety_constraints(prefix: str):
    return (
        CheckConstraint("credential_stored = false", name=f"ck_{prefix}_no_credential"),
        CheckConstraint("oauth_token_exchanged = false", name=f"ck_{prefix}_no_oauth"),
        CheckConstraint("remote_read_performed = false", name=f"ck_{prefix}_no_read"),
        CheckConstraint("remote_write_performed = false", name=f"ck_{prefix}_no_write"),
        CheckConstraint("remote_delete_performed = false", name=f"ck_{prefix}_no_delete"),
        CheckConstraint("subscription_created = false", name=f"ck_{prefix}_no_subscription"),
        CheckConstraint("sync_executed = false", name=f"ck_{prefix}_no_sync"),
        CheckConstraint("evidence_admitted = false", name=f"ck_{prefix}_no_evidence"),
        CheckConstraint("document_created = false", name=f"ck_{prefix}_no_document"),
        CheckConstraint("claim_mutated = false", name=f"ck_{prefix}_no_claim"),
        CheckConstraint("live_connection_authorized = false", name=f"ck_{prefix}_no_live_authority"),
    )


class ExternalDocumentSourceProfile(UUIDPrimaryKeyMixin, TimestampMixin, _ExternalDocumentSourceSafetyMixin, Base):
    __tablename__ = "external_document_source_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_kind", "config_hash", name="uq_ext_doc_source_scope"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_source_provider"),
        CheckConstraint("status IN ('pending_second_approval','active','rejected','disabled')", name="ck_ext_doc_source_status"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_ext_doc_source_four_eyes"),
        CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'active' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'disabled' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_source_lifecycle",
        ),
        Index("ix_ext_doc_source_org_status", "organization_id", "status"),
        Index("ix_ext_doc_source_org_provider", "organization_id", "provider_kind"),
        *_safety_constraints("ext_doc_source"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_second_approval", server_default="pending_second_approval")

    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceProfileReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _ExternalDocumentSourceSafetyMixin, Base):
    __tablename__ = "external_document_source_profile_receipts"
    __table_args__ = (
        UniqueConstraint("profile_id", "sequence_number", name="uq_ext_doc_source_receipt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_source_receipt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_source_receipt_seq"),
        CheckConstraint("event_type IN ('requested','approved','rejected','disabled')", name="ck_ext_doc_source_receipt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval') OR "
            "(event_type = 'approved' AND status_after = 'active') OR "
            "(event_type = 'rejected' AND status_after = 'rejected') OR "
            "(event_type = 'disabled' AND status_after = 'disabled')",
            name="ck_ext_doc_source_receipt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_source_receipt_chain"),
        Index("ix_ext_doc_source_receipt_profile_seq", "profile_id", "sequence_number"),
        *_safety_constraints("ext_doc_source_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceDiscoveryRun(UUIDPrimaryKeyMixin, TimestampMixin, _ExternalDocumentSourceSafetyMixin, Base):
    __tablename__ = "external_document_source_discovery_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_discovery_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_discovery_provider"),
        CheckConstraint("status = 'completed'", name="ck_ext_doc_discovery_status"),
        CheckConstraint("max_results > 0 AND max_results <= 500", name="ck_ext_doc_discovery_limit"),
        CheckConstraint("result_count >= 0 AND result_count <= max_results", name="ck_ext_doc_discovery_count"),
        CheckConstraint("remote_list_performed = true", name="ck_ext_doc_discovery_list_performed"),
        Index("ix_ext_doc_discovery_org_profile", "organization_id", "profile_id"),
        *_non_list_safety_constraints("ext_doc_discovery"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    max_results: Mapped[int] = mapped_column(nullable=False)
    adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed", server_default="completed")
    result_count: Mapped[int] = mapped_column(nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExternalDocumentSourceDiscoveryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_document_source_discovery_items"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_ext_doc_discovery_item_ordinal"),
        UniqueConstraint("run_id", "provider_item_id", name="uq_ext_doc_discovery_item_provider"),
        CheckConstraint("ordinal > 0", name="ck_ext_doc_discovery_item_ordinal"),
        CheckConstraint("item_kind IN ('file','folder')", name="ck_ext_doc_discovery_item_kind"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_ext_doc_discovery_item_size"),
        Index("ix_ext_doc_discovery_item_run_ordinal", "run_id", "ordinal"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_discovery_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    provider_item_id: Mapped[str] = mapped_column(String(512), nullable=False)
    parent_item_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    item_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    item_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceDiscoveryReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _ExternalDocumentSourceSafetyMixin, Base):
    __tablename__ = "external_document_source_discovery_receipts"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_number", name="uq_ext_doc_discovery_receipt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_discovery_receipt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_discovery_receipt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_discovery_receipt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND remote_list_performed = false AND manifest_hash IS NULL AND run_hash IS NULL) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND remote_list_performed = true AND manifest_hash IS NOT NULL AND run_hash IS NOT NULL)",
            name="ck_ext_doc_discovery_receipt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_discovery_receipt_chain"),
        Index("ix_ext_doc_discovery_receipt_run_seq", "run_id", "sequence_number"),
        *_non_list_safety_constraints("ext_doc_discovery_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_discovery_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
