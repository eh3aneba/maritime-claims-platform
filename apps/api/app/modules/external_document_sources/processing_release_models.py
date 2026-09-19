from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _ProcessingReleaseSafetyMixin:
    family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    local_text_processing_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    ai_processing_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_io_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_io_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    return (
        CheckConstraint("family_binding_verified = true", name=f"ck_{prefix}_family"),
        CheckConstraint("current_document_verified = true", name=f"ck_{prefix}_current"),
        CheckConstraint("local_text_processing_authorized = true", name=f"ck_{prefix}_local"),
        CheckConstraint("ai_processing_authorized = false", name=f"ck_{prefix}_no_ai"),
        CheckConstraint("provider_io_performed = false", name=f"ck_{prefix}_no_provider_io"),
        CheckConstraint("storage_io_performed = false", name=f"ck_{prefix}_no_storage_io"),
        CheckConstraint("document_mutated = false", name=f"ck_{prefix}_no_document_mutation"),
        CheckConstraint("processing_enqueued = false", name=f"ck_{prefix}_no_enqueue"),
        CheckConstraint("claim_mutated = false", name=f"ck_{prefix}_no_claim_mutation"),
    )


class ExternalDocumentSourceProcessingRelease(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ProcessingReleaseSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_processing_releases"
    __table_args__ = (
        UniqueConstraint("binding_id", name="uq_ext_doc_proc_release_binding"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_proc_release_request"),
        UniqueConstraint(
            "organization_id",
            "profile_id",
            "revocation_request_key",
            name="uq_ext_doc_proc_release_revoke_request",
        ),
        CheckConstraint("status IN ('active','revoked')", name="ck_ext_doc_proc_release_status"),
        CheckConstraint("document_version_number >= 1", name="ck_ext_doc_proc_release_version"),
        CheckConstraint(
            "(status = 'active' AND revocation_request_key IS NULL AND revoked_by_id IS NULL "
            "AND revocation_reason IS NULL AND revoked_at IS NULL AND terminal_hash IS NULL) OR "
            "(status = 'revoked' AND revocation_request_key IS NOT NULL AND revoked_by_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL AND revoked_at IS NOT NULL AND terminal_hash IS NOT NULL)",
            name="ck_ext_doc_proc_release_revocation_state",
        ),
        Index("ix_ext_doc_proc_release_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_proc_release_document", "organization_id", "document_id"),
        Index("ix_ext_doc_proc_release_family", "organization_id", "document_family_id"),
        *_safety_constraints("ext_doc_proc_release"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    document_version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    released_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    release_reason: Mapped[str] = mapped_column(Text, nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    revocation_request_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalDocumentSourceProcessingReleaseReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ProcessingReleaseSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_processing_release_receipts"
    __table_args__ = (
        UniqueConstraint("release_id", "sequence_number", name="uq_ext_doc_proc_release_rcpt_seq"),
        CheckConstraint("sequence_number IN (1,2)", name="ck_ext_doc_proc_release_rcpt_seq"),
        CheckConstraint("event_type IN ('granted','revoked')", name="ck_ext_doc_proc_release_rcpt_event"),
        CheckConstraint("status_after IN ('active','revoked')", name="ck_ext_doc_proc_release_rcpt_status"),
        CheckConstraint(
            "(sequence_number = 1 AND event_type = 'granted' AND status_after = 'active' "
            "AND prior_receipt_hash IS NULL) OR "
            "(sequence_number = 2 AND event_type = 'revoked' AND status_after = 'revoked' "
            "AND prior_receipt_hash IS NOT NULL)",
            name="ck_ext_doc_proc_release_rcpt_lifecycle",
        ),
        Index("ix_ext_doc_proc_release_rcpt_release", "release_id"),
        *_safety_constraints("ext_doc_proc_release_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_processing_releases.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
