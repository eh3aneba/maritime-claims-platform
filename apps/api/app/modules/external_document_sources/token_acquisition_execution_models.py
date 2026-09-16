from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _TokenAcquisitionSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    credential_reference_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    activation_authorization_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    token_acquisition_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_token_exchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    token_endpoint_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_authorization_code_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    access_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    refresh_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    id_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    client_secret_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    private_key_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_data_api_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
        ("provider_client_constructed", "provider_client"),
        ("provider_data_api_performed", "data_api"),
        ("remote_list_performed", "list"),
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
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceTokenAcquisitionExecution(UUIDPrimaryKeyMixin, TimestampMixin, _TokenAcquisitionSafetyMixin, Base):
    __tablename__ = "external_doc_source_token_acquisition_execs"
    __table_args__ = (
        UniqueConstraint("credential_resolution_execution_id", name="uq_ext_doc_tok_exec_resolution"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_tok_exec_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_tok_exec_provider"),
        CheckConstraint("token_flow_kind IN ('client_credentials','jwt_bearer')", name="ck_ext_doc_tok_exec_flow"),
        CheckConstraint("status IN ('requested','completed')", name="ck_ext_doc_tok_exec_status"),
        CheckConstraint("result_status IS NULL OR result_status = 'acquired'", name="ck_ext_doc_tok_exec_result"),
        CheckConstraint("expiry_class IS NULL OR expiry_class IN ('short','standard','long','unknown')", name="ck_ext_doc_tok_exec_expiry"),
        CheckConstraint(
            "(status = 'requested' AND completed_at IS NULL AND completion_hash IS NULL AND result_status IS NULL AND expiry_class IS NULL AND token_acquisition_performed = false AND oauth_token_exchanged = false AND token_endpoint_network_performed = false) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND completion_hash IS NOT NULL AND result_status = 'acquired' AND expiry_class IS NOT NULL AND token_acquisition_performed = true AND oauth_token_exchanged = true AND token_endpoint_network_performed = true)",
            name="ck_ext_doc_tok_exec_lifecycle",
        ),
        Index("ix_ext_doc_tok_exec_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_tok_exec_org_status", "organization_id", "status"),
        *_safety_constraints("ext_doc_tok_exec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_resolution_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_credential_resolution_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    activation_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_provider_client_activation_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_provider_client_activation_auths.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_credential_reference_health_checks.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_credential_reference_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution_resolver_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_resolution_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_resolution_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_resolution_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_flow_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    acquirer_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested", server_default="requested")
    result_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    expiry_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceTokenAcquisitionExecutionReceipt(UUIDPrimaryKeyMixin, TimestampMixin, _TokenAcquisitionSafetyMixin, Base):
    __tablename__ = "external_doc_source_token_acquisition_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_tok_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_tok_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_tok_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_tok_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND token_acquisition_performed = false AND oauth_token_exchanged = false AND token_endpoint_network_performed = false) OR "
            "(event_type = 'completed' AND status_after = 'completed' AND token_acquisition_performed = true AND oauth_token_exchanged = true AND token_endpoint_network_performed = true)",
            name="ck_ext_doc_tok_rcpt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_tok_rcpt_chain"),
        Index("ix_ext_doc_tok_rcpt_seq", "execution_id", "sequence_number"),
        *_safety_constraints("ext_doc_tok_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_token_acquisition_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
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
