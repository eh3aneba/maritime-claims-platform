from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _RemoteMetadataListingSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    credential_reference_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activation_authorization_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_token_acquisition_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_provider_client_health_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_authorization_code_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    access_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    refresh_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    id_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    client_secret_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    private_key_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_client_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_response_body_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    subscription_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sync_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_stored", "credential"),
        ("oauth_authorization_code_stored", "oauth_code"),
        ("access_token_stored", "access_token"),
        ("refresh_token_stored", "refresh_token"),
        ("id_token_stored", "id_token"),
        ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"),
        ("provider_client_stored", "client_stored"),
        ("provider_response_body_stored", "response_body"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("subscription_created", "subscription"),
        ("checkpoint_created", "checkpoint"),
        ("sync_executed", "sync"),
        ("evidence_admitted", "evidence"),
        ("document_created", "document"),
        ("claim_mutated", "claim"),
    )
    return (
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference"),
        CheckConstraint("credential_reference_resolution_performed = true", name=f"ck_{prefix}_resolved"),
        CheckConstraint("activation_authorization_consumed = true", name=f"ck_{prefix}_consumed"),
        CheckConstraint("upstream_token_acquisition_completed = true", name=f"ck_{prefix}_token_done"),
        CheckConstraint("upstream_provider_client_health_completed = true", name=f"ck_{prefix}_health_done"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceRemoteMetadataListingExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _RemoteMetadataListingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_remote_metadata_list_execs"
    __table_args__ = (
        UniqueConstraint("provider_client_health_execution_id", name="uq_ext_doc_rml_exec_health"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_rml_exec_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_rml_exec_provider"),
        CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_rml_exec_status"),
        CheckConstraint("result_status IS NULL OR result_status = 'listed'", name="ck_ext_doc_rml_exec_result"),
        CheckConstraint("item_count >= 0 AND item_count <= 100", name="ck_ext_doc_rml_exec_item_count"),
        CheckConstraint("page_count >= 0 AND page_count <= 1", name="ck_ext_doc_rml_exec_page_count"),
        CheckConstraint(
            "(status = 'requested' AND completed_at IS NULL AND completion_hash IS NULL AND result_status IS NULL AND item_count = 0 AND page_count = 0 AND truncated = false AND items_hash IS NULL AND provider_client_constructed = false AND remote_list_performed = false) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND result_status = 'listed' AND page_count = 1 AND items_hash IS NOT NULL AND provider_client_constructed = true AND remote_list_performed = true)",
            name="ck_ext_doc_rml_exec_lifecycle",
        ),
        Index("ix_ext_doc_rml_exec_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_rml_exec_org_status", "organization_id", "status"),
        *_safety_constraints("ext_doc_rml_exec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_client_health_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_provider_client_health_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_acquisition_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_token_acquisition_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_resolution_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_credential_resolution_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_credential_reference_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution_resolver_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    token_flow_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    client_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    health_operation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    health_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_client_health_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_client_health_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_client_health_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_operation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    list_adapter_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested", server_default="requested")
    result_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    items_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceRemoteMetadataListingItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_doc_source_remote_metadata_list_items"
    __table_args__ = (
        UniqueConstraint("execution_id", "item_index", name="uq_ext_doc_rml_item_index"),
        UniqueConstraint("execution_id", "item_hash", name="uq_ext_doc_rml_item_hash"),
        CheckConstraint("item_index >= 0 AND item_index < 100", name="ck_ext_doc_rml_item_index"),
        CheckConstraint("item_kind IN ('file','folder')", name="ck_ext_doc_rml_item_kind"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_ext_doc_rml_item_size"),
        Index("ix_ext_doc_rml_item_exec_index", "execution_id", "item_index"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_remote_metadata_list_execs.id", ondelete="CASCADE"), nullable=False, index=True)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_item_id: Mapped[str] = mapped_column(String(512), nullable=False)
    parent_item_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    item_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceRemoteMetadataListingReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _RemoteMetadataListingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_remote_metadata_list_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_rml_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_rml_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_rml_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_rml_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND provider_client_constructed = false AND remote_list_performed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND provider_client_constructed = true AND remote_list_performed = true)",
            name="ck_ext_doc_rml_rcpt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_rml_rcpt_chain"),
        Index("ix_ext_doc_rml_rcpt_seq", "execution_id", "sequence_number"),
        *_safety_constraints("ext_doc_rml_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_remote_metadata_list_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
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
