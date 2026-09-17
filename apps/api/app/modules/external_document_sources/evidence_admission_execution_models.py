from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _EvidenceAdmissionExecutionSafetyMixin:
    upstream_authorization_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authorization_single_use_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    latest_generation_3_observation_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    fresh_exact_item_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    fresh_remote_version_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    staged_content_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    malware_scan_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    canonical_document_write_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    admission_execution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    staged_storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    staged_storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    background_sync_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    always_true = (
        ("upstream_authorization_verified", "auth"),
        ("authorization_single_use_consumed", "single_use"),
        ("latest_generation_3_observation_confirmed", "latest"),
        ("fresh_exact_item_metadata_read_performed", "metadata"),
        ("fresh_remote_version_current", "current"),
        ("staged_content_integrity_verified", "staged_integrity"),
        ("malware_scan_completed", "malware"),
        ("canonical_document_write_completed", "canonical_write"),
        ("document_created", "document"),
        ("evidence_admitted", "evidence"),
        ("admission_execution_performed", "execution"),
    )
    always_false = (
        ("remote_list_performed", "list"),
        ("remote_content_read_performed", "remote_content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("staged_storage_write_performed", "staged_write"),
        ("staged_storage_delete_performed", "staged_delete"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
        ("processing_enqueued", "processing"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_sync_started", "background"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in always_true),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in always_false),
    )


class ExternalDocumentSourceEvidenceAdmissionExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _EvidenceAdmissionExecutionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_evidence_admission_execs"
    __table_args__ = (
        UniqueConstraint("authorization_id", name="uq_ext_doc_eae_authorization"),
        UniqueConstraint("document_id", name="uq_ext_doc_eae_document"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_eae_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_eae_provider"),
        CheckConstraint("status = 'admitted'", name="ck_ext_doc_eae_status"),
        CheckConstraint("fresh_byte_size >= 0", name="ck_ext_doc_eae_fresh_size"),
        CheckConstraint("staged_content_byte_count >= 0", name="ck_ext_doc_eae_staged_size"),
        CheckConstraint("document_file_size_bytes >= 0", name="ck_ext_doc_eae_document_size"),
        Index("ix_ext_doc_eae_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_eae_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_eae_authorization", "authorization_id"),
        Index("ix_ext_doc_eae_document", "document_id"),
        *_safety_constraints("ext_doc_eae"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_admission_auths.id", ondelete="RESTRICT"), nullable=False, index=True)
    generation_3_change_detection_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_gen3_change_detect_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    checkpoint_generation_3_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_checkpoint_gen3_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    successor_versioned_restaging_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_successor_versioned_restage_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    fresh_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fresh_display_name_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fresh_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fresh_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fresh_mime_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)

    staged_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    staged_content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    staged_storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_filename_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_storage_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="admitted", server_default="admitted")
    executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_reason: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceEvidenceAdmissionExecutionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _EvidenceAdmissionExecutionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_evidence_admission_exec_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_eae_receipt_sequence"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_eae_receipt_sequence"),
        CheckConstraint("event_type = 'admitted'", name="ck_ext_doc_eae_receipt_event"),
        CheckConstraint("status_after = 'admitted'", name="ck_ext_doc_eae_receipt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_eae_receipt_prior"),
        Index("ix_ext_doc_eae_receipt_execution", "execution_id"),
        *_safety_constraints("ext_doc_eae_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_admission_execs.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="admitted", server_default="admitted")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="admitted", server_default="admitted")
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)