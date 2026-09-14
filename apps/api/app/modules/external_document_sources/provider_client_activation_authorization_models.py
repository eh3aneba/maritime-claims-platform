from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ProviderClientActivationAuthorizationSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    credential_reference_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_authorization_code_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_token_exchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    access_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    refresh_token_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    client_secret_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    private_key_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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
    provider_client_activation_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    false_fields = (
        ("credential_reference_resolution_performed", "resolution"),
        ("credential_stored", "credential"),
        ("oauth_authorization_code_stored", "oauth_code"),
        ("oauth_token_exchanged", "oauth"),
        ("access_token_stored", "access_token"),
        ("refresh_token_stored", "refresh_token"),
        ("client_secret_stored", "client_secret"),
        ("private_key_stored", "private_key"),
        ("provider_network_performed", "provider_network"),
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
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceProviderClientActivationAuthorization(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ProviderClientActivationAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_document_source_provider_client_activation_auths"
    __table_args__ = (
        UniqueConstraint("health_qualification_id", name="uq_ext_doc_pc_act_health"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_pc_act_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_pc_act_provider"),
        CheckConstraint("health_result_status = 'resolvable'", name="ck_ext_doc_pc_act_resolvable"),
        CheckConstraint("status IN ('pending_second_approval','authorized','rejected','expired')", name="ck_ext_doc_pc_act_status"),
        CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_ext_doc_pc_act_four_eyes"),
        CheckConstraint("execution_limit = 1", name="ck_ext_doc_pc_act_limit"),
        CheckConstraint(
            "(status = 'authorized' AND provider_client_activation_authorized = true) OR "
            "(status <> 'authorized' AND provider_client_activation_authorized = false)",
            name="ck_ext_doc_pc_act_auth_mapping",
        ),
        CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND authorization_hash IS NULL AND authorization_expires_at IS NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'authorized' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL AND approval_reason IS NOT NULL AND authorization_hash IS NOT NULL AND authorization_expires_at IS NOT NULL AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL AND approval_reason IS NULL AND authorization_hash IS NULL AND authorization_expires_at IS NULL AND terminal_by_id IS NOT NULL AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL) OR "
            "(status = 'expired' AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_pc_act_lifecycle",
        ),
        Index("ix_ext_doc_pc_act_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_pc_act_org_status", "organization_id", "status"),
        *_safety_constraints("ext_doc_pc_act"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    health_qualification_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_credential_reference_health_checks.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_credential_reference_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_approval_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    resolver_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    health_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    health_result_status: Mapped[str] = mapped_column(String(24), nullable=False)

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


class ExternalDocumentSourceProviderClientActivationAuthorizationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ProviderClientActivationAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_provider_client_activation_receipts"
    __table_args__ = (
        UniqueConstraint("authorization_id", "sequence_number", name="uq_ext_doc_pc_act_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_pc_act_rcpt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_pc_act_rcpt_seq"),
        CheckConstraint("event_type IN ('requested','authorized','rejected','expired')", name="ck_ext_doc_pc_act_rcpt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval' AND provider_client_activation_authorized = false) OR "
            "(event_type = 'authorized' AND status_after = 'authorized' AND provider_client_activation_authorized = true) OR "
            "(event_type = 'rejected' AND status_after = 'rejected' AND provider_client_activation_authorized = false) OR "
            "(event_type = 'expired' AND status_after = 'expired' AND provider_client_activation_authorized = false)",
            name="ck_ext_doc_pc_act_rcpt_mapping",
        ),
        CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_ext_doc_pc_act_rcpt_chain"),
        Index("ix_ext_doc_pc_act_rcpt_seq", "authorization_id", "sequence_number"),
        *_safety_constraints("ext_doc_pc_act_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_provider_client_activation_auths.id", ondelete="RESTRICT"), nullable=False, index=True)
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
