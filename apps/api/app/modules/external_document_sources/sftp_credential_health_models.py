from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SftpCredentialHealthSafetyMixin:
    credential_reference_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    secret_resolution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


def _non_secret_safety_constraints(prefix: str):
    fields = (
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
        CheckConstraint("credential_reference_stored = true", name=f"ck_{prefix}_reference_only"),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in fields),
    )


class ExternalDocumentSourceSftpCredentialHealthQualification(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpCredentialHealthSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_cred_health_checks"
    __table_args__ = (
        UniqueConstraint("credential_reference_binding_id", name="uq_ext_doc_sftp_cred_health_binding"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_sftp_cred_health_request"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_ext_doc_sftp_cred_health_provider"),
        CheckConstraint("authentication_kind IN ('password','private_key')", name="ck_ext_doc_sftp_cred_health_auth"),
        CheckConstraint(
            "reference_backend IN ('aws_secrets_manager','azure_key_vault','gcp_secret_manager','hashicorp_vault')",
            name="ck_ext_doc_sftp_cred_health_backend",
        ),
        CheckConstraint("result_status IN ('qualified','unqualified')", name="ck_ext_doc_sftp_cred_health_result"),
        CheckConstraint(
            "(result_status = 'qualified' AND failure_code IS NULL AND resolved_material_kind = authentication_kind) OR "
            "(result_status = 'unqualified' AND failure_code IS NOT NULL)",
            name="ck_ext_doc_sftp_cred_health_outcome",
        ),
        CheckConstraint(
            "resolved_material_kind IS NULL OR resolved_material_kind IN ('password','private_key')",
            name="ck_ext_doc_sftp_cred_health_material_kind",
        ),
        CheckConstraint("checked_at >= requested_at", name="ck_ext_doc_sftp_cred_health_time"),
        CheckConstraint("secret_resolution_performed = true", name="ck_ext_doc_sftp_cred_health_resolution"),
        Index("ix_ext_doc_sftp_cred_health_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_sftp_cred_health_org_result", "organization_id", "result_status"),
        *_non_secret_safety_constraints("ext_doc_sftp_cred_health"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_reference_binding_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_sftp_cred_ref_bindings.id", ondelete="RESTRICT"),
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

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_material_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpCredentialHealthReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpCredentialHealthSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_cred_health_receipts"
    __table_args__ = (
        UniqueConstraint("qualification_id", "sequence_number", name="uq_ext_doc_sftp_cred_health_receipt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_ext_doc_sftp_cred_health_receipt_hash"),
        CheckConstraint("sequence_number > 0", name="ck_ext_doc_sftp_cred_health_receipt_seq"),
        CheckConstraint("event_type IN ('requested','completed')", name="ck_ext_doc_sftp_cred_health_receipt_event"),
        CheckConstraint(
            "(event_type = 'requested' AND status_after = 'requested' AND secret_resolution_performed = false) OR "
            "(event_type = 'completed' AND status_after IN ('qualified','unqualified') AND secret_resolution_performed = true)",
            name="ck_ext_doc_sftp_cred_health_receipt_mapping",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_sftp_cred_health_receipt_chain",
        ),
        Index("ix_ext_doc_sftp_cred_health_receipt_qual_seq", "qualification_id", "sequence_number"),
        *_non_secret_safety_constraints("ext_doc_sftp_cred_health_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    qualification_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_sftp_cred_health_checks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
