from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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


class _EvidenceFamilyBindingSafetyMixin:
    upstream_admission_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    stable_source_identity_derived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    document_family_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    version_baseline_recorded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    provider_client_constructed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_metadata_read_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_content_read_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_write_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    remote_delete_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    storage_read_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    storage_write_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    storage_delete_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    document_created: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    document_mutated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    processing_enqueued: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    content_extracted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    ai_executed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    claim_mutated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    checkpoint_advanced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    background_sync_started: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


def _safety_constraints(prefix: str):
    always_true = (
        ("upstream_admission_verified", "admission"),
        ("stable_source_identity_derived", "identity"),
        ("document_family_verified", "family"),
        ("version_baseline_recorded", "baseline"),
    )
    always_false = (
        ("provider_client_constructed", "client"),
        ("remote_metadata_read_performed", "metadata"),
        ("remote_content_read_performed", "remote_content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("document_created", "document_create"),
        ("document_mutated", "document_mutate"),
        ("processing_enqueued", "processing"),
        ("content_extracted", "extract"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_sync_started", "background"),
    )
    return (
        *(
            CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}")
            for field, suffix in always_true
        ),
        *(
            CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}")
            for field, suffix in always_false
        ),
    )


class ExternalDocumentSourceEvidenceFamilyBinding(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _EvidenceFamilyBindingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_evidence_family_bindings"
    __table_args__ = (
        UniqueConstraint("admission_execution_id", name="uq_ext_doc_efb_admission"),
        UniqueConstraint("initial_document_id", name="uq_ext_doc_efb_initial_doc"),
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "profile_id",
            "stable_source_item_hash",
            name="uq_ext_doc_efb_source",
        ),
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "document_family_id",
            name="uq_ext_doc_efb_family",
        ),
        UniqueConstraint(
            "organization_id",
            "profile_id",
            "request_key",
            name="uq_ext_doc_efb_request",
        ),
        CheckConstraint(
            "provider_kind IN ('sharepoint','google_drive')",
            name="ck_ext_doc_efb_provider",
        ),
        CheckConstraint("status = 'active'", name="ck_ext_doc_efb_status"),
        CheckConstraint("current_version_number = 1", name="ck_ext_doc_efb_version"),
        CheckConstraint("admitted_byte_count >= 0", name="ck_ext_doc_efb_size"),
        Index("ix_ext_doc_efb_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_efb_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_efb_source", "stable_source_item_hash"),
        Index("ix_ext_doc_efb_family", "document_family_id"),
        *_safety_constraints("ext_doc_efb"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    admission_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_evidence_admission_execs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    initial_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_family_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    current_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    admitted_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    admitted_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admitted_mime_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    admitted_provider_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", server_default="active"
    )
    bound_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    binding_reason: Mapped[str] = mapped_column(Text, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceEvidenceFamilyBindingReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _EvidenceFamilyBindingSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_evidence_family_binding_receipts"
    __table_args__ = (
        UniqueConstraint("binding_id", "sequence_number", name="uq_ext_doc_efb_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_efb_rcpt_seq"),
        CheckConstraint("event_type = 'bound'", name="ck_ext_doc_efb_rcpt_event"),
        CheckConstraint("status_after = 'active'", name="ck_ext_doc_efb_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_efb_rcpt_prior"),
        Index("ix_ext_doc_efb_rcpt_binding", "binding_id"),
        *_safety_constraints("ext_doc_efb_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    binding_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    event_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="bound", server_default="bound"
    )
    status_after: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", server_default="active"
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
